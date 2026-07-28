"""Market-hours scheduler for the CLI bot runtime."""

from datetime import datetime
from time import sleep

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import is_bist_open
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
                    logger.info("scheduler_market_closed_idle")
                    sleep(60)
                    continue

                minute = now.minute
                warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)
                half_day_hour = getattr(self.settings, "MARKET_HALF_DAY_HOUR", 13)

                if minute < warmup_minutes and now.hour == self.settings.MARKET_OPEN_HOUR:
                    logger.info(
                        "scheduler_warmup_wait",
                        warmup_minutes=warmup_minutes,
                    )
                    sleep(60)
                    continue

                if now.hour >= half_day_hour and now.hour < self.settings.MARKET_CLOSE_HOUR:
                    logger.info("scheduler_half_day_scan_window")
                    self._scan_once()
                    sleep(3600 * (self.settings.MARKET_CLOSE_HOUR - half_day_hour))
                    continue

                try:
                    self._scan_once()
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

                CHECK_INTERVAL_SECONDS = 10
                total_wait_seconds = self.settings.SCAN_INTERVAL_MINUTES * 60
                max_iterations = total_wait_seconds // CHECK_INTERVAL_SECONDS
                for _ in range(max_iterations):
                    if not self.running:
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
