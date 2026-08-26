"""Market-hours scheduler for the CLI bot runtime.

Faz 4 hardened runtime:
- EOD pass: session-close trigger (bist_eod_time), failure ≠ done, bounded
  retry, Telegram escalation on final failure (B2).
- Scan watchdog: no successful scan during market hours for
  WATCHDOG_STALE_MINUTES → Telegram alert with cooldown + recovery message (C3).
- Retry exhaustion: Telegram escalation + metric + recovery event (C4).
- Grid alignment keeps a minimum separation from the previous scan so a
  startup scan never doubles with the next grid slot (C5).
"""

import datetime as _datetime_mod
from datetime import date, datetime, timedelta
from time import sleep

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter, set_gauge
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import (
    bist_eod_time,
    is_bist_holiday,
    is_bist_open,
    next_bist_session,
    warn_if_calendar_expiring,
)
from bist_bot.notifier import TR

logger = get_logger(__name__, component="scheduler")

METRIC_EOD_FAIL = "bist_eod_fail_total"
METRIC_RETRY_EXHAUSTED = "bist_scan_retry_exhausted_total"
METRIC_WATCHDOG_ALERT = "bist_watchdog_alert_total"
METRIC_WATCHDOG_RECOVERED = "bist_watchdog_recovered_total"
METRIC_ALERT_SEND_FAIL = "bist_alert_send_fail_total"
GAUGE_LAST_SCAN_TS = "bist_last_scan_success_timestamp"


class MarketScheduler:
    def __init__(self, scan_service, notifier, settings=default_settings, trading_agent=None):
        self.scanner = scan_service
        self.notifier = notifier
        self.settings = settings
        self.trading_agent = trading_agent
        self.running = False
        # Faz 3 P1.1: post-close position pass fires once per trading day.
        self._eod_close_done_date: date | None = None
        # B2: EOD failure state — a failed pass must NOT mark the day done.
        self._eod_state_date: date | None = None
        self._eod_fail_count = 0
        self._eod_next_retry_at: datetime | None = None
        self._eod_final_failed = False
        # C3/C4 runtime health state.
        self._last_scan_success_at: datetime | None = None
        self._last_scan_attempt_at: datetime | None = None
        self._watchdog_alerted_at: datetime | None = None
        self._scan_fail_streak = False

    def _now(self) -> datetime:
        return datetime.now(TR)

    def _notify(self, text: str) -> None:
        """Send a Telegram ops alert; a silent channel is itself measurable."""
        try:
            sent = self.notifier.send_message(text)
        except Exception:
            sent = False
        if not sent:
            inc_counter(METRIC_ALERT_SEND_FAIL)
            logger.error("scheduler_alert_send_failed", preview=text[:60])

    # ------------------------------------------------------------------
    # EOD pass (B2)
    # ------------------------------------------------------------------
    def _eod_trigger_time(self, d: date) -> datetime | None:
        """Session close + delay trigger for the daily EOD pass; None on holidays."""
        if is_bist_holiday(d):
            return None
        # Use the real datetime module (not the patchable module-level name)
        # so combine() works even when tests stub `datetime` with a minimal class.
        return _datetime_mod.datetime.combine(d, bist_eod_time(d), tzinfo=TR)

    def _reset_eod_state_for_date(self, now: datetime) -> None:
        if self._eod_state_date != now.date():
            self._eod_state_date = now.date()
            self._eod_fail_count = 0
            self._eod_next_retry_at = None
            self._eod_final_failed = False

    def _pending_eod_close(self, now: datetime) -> bool:
        """True when the EOD pass is due: after trigger, not yet succeeded."""
        self._reset_eod_state_for_date(now)
        trigger = self._eod_trigger_time(now.date())
        if trigger is None or now < trigger:
            return False
        if self._eod_close_done_date == now.date():
            return False
        if self._eod_final_failed:
            return False
        return self._eod_next_retry_at is None or now >= self._eod_next_retry_at

    def _run_eod_close(self, now: datetime) -> None:
        if not self._pending_eod_close(now):
            return
        logger.info("scheduler_eod_close_started", date=now.date().isoformat())
        max_attempts = max(1, int(getattr(self.settings, "EOD_MAX_ATTEMPTS", 2)))
        retry_minutes = max(1, int(getattr(self.settings, "EOD_RETRY_MINUTES", 8)))
        try:
            closer = getattr(self.scanner, "close_positions_at_eod", None)
            if callable(closer):
                closer()
            else:
                logger.warning("scheduler_eod_close_unavailable")
        except Exception as exc:
            self._eod_fail_count += 1
            inc_counter(METRIC_EOD_FAIL)
            logger.error(
                "scheduler_eod_close_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                attempt=self._eod_fail_count,
            )
            if self._eod_fail_count >= max_attempts:
                # FAILED_FINAL: the day is NOT marked done — pozisyonlar açık
                # kalabilir, bu sessiz kalamaz.
                self._eod_final_failed = True
                self._eod_next_retry_at = None
                self._notify(
                    f"🚨 EOD kapanış pass'i {max_attempts} denemede başarısız "
                    f"({now.date().isoformat()}). Paper pozisyonlar açık kaldı — kontrol et!"
                )
            else:
                self._eod_next_retry_at = now + timedelta(minutes=retry_minutes)
                self._notify(
                    f"⚠️ EOD kapanış pass'i hata verdi (deneme {self._eod_fail_count}/{max_attempts}), "
                    f"{retry_minutes} dk sonra tekrar denenecek."
                )
            return
        self._eod_close_done_date = now.date()
        recovered = self._eod_fail_count > 0
        self._eod_fail_count = 0
        self._eod_next_retry_at = None
        if recovered:
            logger.info("scheduler_eod_close_recovered_after_retry")
        logger.info("scheduler_eod_close_completed")

    # ------------------------------------------------------------------
    # Watchdog (C3)
    # ------------------------------------------------------------------
    def _check_watchdog(self, now: datetime) -> None:
        if self._last_scan_success_at is None:
            return
        stale_minutes = max(5, int(getattr(self.settings, "WATCHDOG_STALE_MINUTES", 30)))
        cooldown_minutes = max(stale_minutes, int(getattr(self.settings, "WATCHDOG_ALERT_COOLDOWN_MINUTES", 60)))
        age = (now - self._last_scan_success_at).total_seconds() / 60.0
        if age < stale_minutes:
            return
        if self._watchdog_alerted_at is not None:
            if (now - self._watchdog_alerted_at).total_seconds() / 60.0 < cooldown_minutes:
                return
        self._watchdog_alerted_at = now
        inc_counter(METRIC_WATCHDOG_ALERT)
        logger.error("scheduler_watchdog_scan_stale", stale_minutes=round(age, 1))
        self._notify(
            f"⏰ <b>Watchdog:</b> seans içinde {int(age)} dakikadır başarılı tarama yok. "
            f"Bot taramıyor olabilir — kontrol et!"
        )

    def _mark_scan_success(self, now: datetime) -> None:
        first_or_recovered = self._watchdog_alerted_at is not None or self._scan_fail_streak
        self._last_scan_success_at = now
        set_gauge(GAUGE_LAST_SCAN_TS, now.timestamp())
        if self._watchdog_alerted_at is not None:
            self._watchdog_alerted_at = None
            inc_counter(METRIC_WATCHDOG_RECOVERED)
        if self._scan_fail_streak:
            self._scan_fail_streak = False
        if first_or_recovered:
            self._notify("✅ Tarama geri geldi (watchdog/retry toparlandı).")

    # ------------------------------------------------------------------
    # Session sleep + scan loop
    # ------------------------------------------------------------------
    def _sleep_until_next_session(self) -> None:
        """Sleep until the next BIST session opens, checking self.running periodically."""
        now = self._now()
        next_session = next_bist_session(now)
        wait_seconds = max((next_session - now).total_seconds(), 10)
        logger.info(
            "scheduler_market_closed",
            next_session=next_session.isoformat(),
            sleep_seconds=int(wait_seconds),
        )
        deadline = now.timestamp() + wait_seconds
        while self.running and datetime.now(TR).timestamp() < deadline:
            # Faz 3 P1.1: hand control back when the EOD pass comes due,
            # so a position never survives the session while we idle.
            if self._pending_eod_close(datetime.now(TR)):
                return
            sleep(10)

    def _scan_once(self):
        signals = self.scanner.scan_once()
        if self.trading_agent is not None:
            self.trading_agent.on_scan_completed(signals)
        return signals

    def run_loop(self):
        self.running = True

        logger.info("scheduler_started")
        warn_if_calendar_expiring()
        self.notifier.send_startup_message()

        while self.running:
            try:
                now = self._now()

                # Faz 3 P1.1: post-close pass — must be evaluated BEFORE the
                # idle-sleep branch, otherwise the scheduler would jump
                # straight to tomorrow and the EOD contract could never fire.
                if self._pending_eod_close(now):
                    self._run_eod_close(now)
                    continue

                if not is_bist_open(now):
                    self._sleep_until_next_session()
                    continue

                self._check_watchdog(now)

                minute = now.minute
                warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)

                if minute < warmup_minutes and now.hour == self.settings.MARKET_OPEN_HOUR:
                    logger.info(
                        "scheduler_warmup_wait",
                        warmup_minutes=warmup_minutes,
                    )
                    sleep(60)
                    continue

                self._last_scan_attempt_at = now
                try:
                    self._scan_once()
                    self._mark_scan_success(self._now())
                except Exception as e:
                    logger.error(
                        "scheduler_scan_failed",
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    self._notify("⚠️ Tarama hatası oluştu. Birkaç dakika sonra yeniden deneniyor.")
                    for attempt in range(1, 4):
                        if not self.running:
                            break
                        backoff = 30 * attempt
                        logger.info(
                            "scheduler_scan_retry",
                            attempt=attempt,
                            backoff_seconds=backoff,
                        )
                        sleep(backoff)
                        try:
                            self._scan_once()
                            self._mark_scan_success(self._now())
                            logger.info("scheduler_scan_retry_succeeded", attempt=attempt)
                            break
                        except Exception as retry_exc:
                            logger.error(
                                "scheduler_scan_retry_failed",
                                attempt=attempt,
                                error_type=type(retry_exc).__name__,
                            )
                    else:
                        logger.error("scheduler_scan_exhausted_retries")
                        inc_counter(METRIC_RETRY_EXHAUSTED)
                        self._scan_fail_streak = True
                        self._notify(
                            "🚨 Tarama 3 denemede de başarısız — veri kaynağı/servis kontrol et!"
                        )

                logger.info(
                    "scheduler_next_scan_wait",
                    scan_interval_minutes=self.settings.SCAN_INTERVAL_MINUTES,
                )

                # Align the next scan to the wall-clock grid (e.g. :00/:15/:30/:45)
                # instead of sleeping a full interval after scan completion. This
                # removes cumulative drift. C5: keep a minimum separation from the
                # previous scan so a startup scan never doubles with the next slot.
                CHECK_INTERVAL_SECONDS = 10
                interval_minutes = max(1, int(getattr(self.settings, "SCAN_INTERVAL_MINUTES", 15)))
                interval_seconds = interval_minutes * 60
                min_separation = max(
                    0, int(getattr(self.settings, "SCAN_MIN_SEPARATION_MINUTES", 5))
                ) * 60
                now = self._now()
                seconds_into_cycle = (now.minute * 60 + now.second) % interval_seconds
                wait_seconds = interval_seconds - seconds_into_cycle
                if wait_seconds <= 0:
                    wait_seconds = interval_seconds
                last = self._last_scan_attempt_at
                if last is not None and min_separation > 0:
                    while (
                        now.timestamp() + wait_seconds - last.timestamp()
                    ) < min_separation:
                        wait_seconds += interval_seconds
                deadline = now.timestamp() + wait_seconds
                while self.running and self._now().timestamp() < deadline:
                    # Faz 3 P1.1: a scan finishing just before close must not
                    # sleep through the EOD pass window.
                    if self._pending_eod_close(self._now()):
                        break
                    sleep(CHECK_INTERVAL_SECONDS)

            except Exception as exc:
                logger.exception(
                    "scheduler_loop_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                sleep(60)

        logger.info("scheduler_stopped")
