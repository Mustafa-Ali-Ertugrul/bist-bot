"""US market-hours scheduler for NYSE/NASDAQ (DST-safe via exchange_calendars)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import sleep

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar_us import is_us_market_holiday, is_us_market_open, next_us_session

logger = get_logger(__name__, component="scheduler_us")


class USMarketScheduler:
    """Market-hours scheduler for the US (NYSE/NASDAQ).

    Uses exchange_calendars XNYS calendar so DST transitions are handled
    automatically. Never hardcodes Eastern open/close wall-clock times.
    """

    def __init__(self, scan_service, notifier, settings=default_settings):
        self.scanner = scan_service
        self.notifier = notifier
        self.settings = settings
        self.running = False

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def run_loop(self):
        self.running = True
        logger.info("scheduler_us_started")
        self.notifier.send_startup_message()

        warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)
        scan_interval = self.settings.SCAN_INTERVAL_MINUTES * 60
        check_interval = 10

        while self.running:
            now = self._now()

            if is_us_market_holiday(now):
                logger.info("scheduler_us_holiday_idle")
                next_session = next_us_session(now)
                wait_seconds = max(60, min((next_session - now).total_seconds(), 3600))
                sleep(wait_seconds)
                continue

            if not is_us_market_open(now):
                logger.info("scheduler_us_market_closed")
                next_session = next_us_session(now)
                wait_seconds = max(60, min((next_session - now).total_seconds(), 3600 * 14))
                sleep(wait_seconds)
                continue

            # Market is open: respect optional warmup window
            import exchange_calendars as xcals

            nyse = xcals.get_calendar("XNYS")
            today = now.date()
            try:
                schedule = nyse.schedule.loc[today]
                market_open = schedule.open.astimezone(UTC).to_pydatetime()
                warmup_end = market_open + __import__("datetime").timedelta(minutes=warmup_minutes)
            except Exception:
                warmup_end = None

            if warmup_end and now < warmup_end:
                wait = (warmup_end - now).total_seconds()
                logger.info("scheduler_us_warmup_wait", warmup_seconds=wait)
                sleep(max(60, wait))
                continue

            try:
                self.scanner.scan_once()
            except Exception as e:
                logger.error("scheduler_us_scan_failed", error_type=type(e).__name__)
                self.notifier.send_message(f"⚠️ US bot hatası: {e}")
                for attempt in range(1, 4):
                    if not self.running:
                        break
                    backoff = 30 * attempt
                    logger.info("scheduler_us_scan_retry", attempt=attempt, backoff_seconds=backoff)
                    sleep(backoff)
                    try:
                        self.scanner.scan_once()
                        logger.info("scheduler_us_scan_retry_succeeded", attempt=attempt)
                        break
                    except Exception as retry_exc:
                        logger.error(
                            "scheduler_us_scan_retry_failed",
                            attempt=attempt,
                            error_type=type(retry_exc).__name__,
                        )
                else:
                    logger.error("scheduler_us_scan_exhausted_retries")

            logger.info("scheduler_us_next_scan_wait", scan_interval_seconds=scan_interval)
            iterations = scan_interval // check_interval
            for _ in range(iterations):
                if not self.running:
                    break
                sleep(check_interval)

        logger.info("scheduler_us_stopped")
