"""Market-hours scheduler for the CLI bot runtime."""

from datetime import datetime
from time import sleep

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import is_bist_open, next_bist_session
from bist_bot.notifier import TR

logger = get_logger(__name__, component="scheduler")


class MarketScheduler:
    def __init__(self, scan_service, notifier, settings=default_settings, trading_agent=None):
        self.scanner = scan_service
        self.notifier = notifier
        self.settings = settings
        self.trading_agent = trading_agent
        self.running = False

    def _now(self) -> datetime:
        return datetime.now(TR)

    def _sleep_until_next_session(self) -> None:
        """Sleep until the next BIST session opens, checking self.running periodically for clean shutdown."""
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
            sleep(10)

    def _scan_once(self):
        signals = self.scanner.scan_once()
        if self.trading_agent is not None:
            self.trading_agent.on_scan_completed(signals)
        return signals

    def run_loop(self):
        self.running = True

        logger.info("scheduler_started")
        self.notifier.send_startup_message()

        while self.running:
            try:
                now = self._now()

                if not is_bist_open(now):
                    self._sleep_until_next_session()
                    continue

                minute = now.minute
                warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)

                if minute < warmup_minutes and now.hour == self.settings.MARKET_OPEN_HOUR:
                    logger.info(
                        "scheduler_warmup_wait",
                        warmup_minutes=warmup_minutes,
                    )
                    sleep(60)
                    continue

                try:
                    self._scan_once()
                except Exception as e:
                    logger.error(
                        "scheduler_scan_failed",
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    self.notifier.send_message(
                        "⚠️ Tarama hatası oluştu. Birkaç dakika sonra yeniden deneniyor."
                    )
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

                logger.info(
                    "scheduler_next_scan_wait",
                    scan_interval_minutes=self.settings.SCAN_INTERVAL_MINUTES,
                )

                # Align the next scan to the 15-minute wall-clock grid
                # (:00/:15/:30/:45) instead of sleeping a full interval after
                # scan completion. This removes cumulative drift: scans that
                # take a few seconds no longer push every later scan later.
                CHECK_INTERVAL_SECONDS = 10
                interval_minutes = max(1, int(getattr(self.settings, "SCAN_INTERVAL_MINUTES", 15)))
                interval_seconds = interval_minutes * 60
                now = self._now()
                seconds_into_cycle = (now.minute * 60 + now.second) % interval_seconds
                wait_seconds = interval_seconds - seconds_into_cycle
                if wait_seconds <= 0:
                    wait_seconds = interval_seconds
                deadline = now.timestamp() + wait_seconds
                while self.running and self._now().timestamp() < deadline:
                    sleep(CHECK_INTERVAL_SECONDS)

            except Exception as exc:
                logger.exception(
                    "scheduler_loop_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                sleep(60)

        logger.info("scheduler_stopped")
