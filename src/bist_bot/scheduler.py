"""Market-hours scheduler for the CLI bot runtime."""

from datetime import datetime
from time import sleep

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.notifier import TR

logger = get_logger(__name__, component="scheduler")


class MarketScheduler:
    def __init__(self, scan_service, notifier, settings=default_settings):
        self.scanner = scan_service
        self.notifier = notifier
        self.settings = settings
        self.running = False

    def _now(self) -> datetime:
        return datetime.now(TR)

    def run_loop(self):
        self.running = True

        logger.info("scheduler_started")
        self.notifier.send_startup_message()

        while self.running:
            now = self._now()
            hour = now.hour
            minute = now.minute

            weekday = now.weekday()

            if weekday >= 5:
                logger.info("scheduler_weekend_idle")
                sleep(3600)
                continue

            if hour < self.settings.MARKET_OPEN_HOUR:
                wait = (self.settings.MARKET_OPEN_HOUR - hour) * 3600
                logger.info(
                    "scheduler_pre_market_wait",
                    market_open_hour=self.settings.MARKET_OPEN_HOUR,
                )
                sleep(min(wait, 1800))
                continue

            warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)
            half_day_hour = getattr(self.settings, "MARKET_HALF_DAY_HOUR", 13)

            if hour >= self.settings.MARKET_CLOSE_HOUR:
                logger.info("scheduler_market_closed")
                self.scanner.scan_once()
                sleep(3600 * 14)
                continue

            if hour == self.settings.MARKET_OPEN_HOUR and minute < warmup_minutes:
                logger.info(
                    "scheduler_warmup_wait",
                    warmup_minutes=warmup_minutes,
                )
                sleep(60)
                continue

            if hour >= half_day_hour and hour < self.settings.MARKET_CLOSE_HOUR:
                logger.info("scheduler_half_day_scan_window")
                self.scanner.scan_once()
                sleep(3600 * (self.settings.MARKET_CLOSE_HOUR - half_day_hour))
                continue

            try:
                self.scanner.scan_once()
            except Exception as e:
                logger.error("scheduler_scan_failed", error_type=type(e).__name__)
                self.notifier.send_message(f"⚠️ Bot hatası: {e}")
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
                        self.scanner.scan_once()
                        logger.info(
                            "scheduler_scan_retry_succeeded", attempt=attempt
                        )
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

            CHECK_INTERVAL_SECONDS = 10
            total_wait_seconds = self.settings.SCAN_INTERVAL_MINUTES * 60
            max_iterations = total_wait_seconds // CHECK_INTERVAL_SECONDS
            for _ in range(max_iterations):
                if not self.running:
                    break
                sleep(CHECK_INTERVAL_SECONDS)

        logger.info("scheduler_stopped")
