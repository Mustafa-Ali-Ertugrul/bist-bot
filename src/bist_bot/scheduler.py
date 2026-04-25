"""Market-hours scheduler for the CLI bot runtime."""

import logging
from datetime import datetime, timedelta, timezone
from time import sleep

from bist_bot.config.settings import settings as default_settings

logger = logging.getLogger(__name__)

TR = timezone(timedelta(hours=3))


class MarketScheduler:
    def __init__(self, scan_service, notifier, settings=default_settings):
        self.scanner = scan_service
        self.notifier = notifier
        self.settings = settings
        self.running = False

    def run_loop(self):
        self.running = True

        logger.info("≡ƒÜÇ BIST Bot ba┼ƒlat─▒l─▒yor...")
        self.notifier.send_startup_message()

        while self.running:
            now = datetime.now(TR)
            hour = now.hour
            minute = now.minute

            weekday = now.weekday()

            if weekday >= 5:
                logger.info("≡ƒôà Hafta sonu ΓÇö tarama yap─▒lm─▒yor")
                sleep(3600)
                continue

            if hour < self.settings.MARKET_OPEN_HOUR:
                wait = (self.settings.MARKET_OPEN_HOUR - hour) * 3600
                logger.info(
                    f"ΓÅ░ Borsa hen├╝z a├º─▒lmad─▒. {self.settings.MARKET_OPEN_HOUR}:00'da ba┼ƒlayacak..."
                )
                sleep(min(wait, 1800))
                continue

            warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)
            half_day_hour = getattr(self.settings, "MARKET_HALF_DAY_HOUR", 13)

            if hour >= self.settings.MARKET_CLOSE_HOUR:
                logger.info("≡ƒîÖ Borsa kapand─▒. Yar─▒n g├╢r├╝┼ƒ├╝r├╝z!")
                self.scanner.scan_once()
                sleep(3600 * 14)
                continue

            if hour == self.settings.MARKET_OPEN_HOUR and minute < warmup_minutes:
                logger.info(f"≡ƒîà A├º─▒l─▒┼ƒ g├╝r├╝lt├╝s├╝ - ilk {warmup_minutes} dakika bekleniyor...")
                sleep(60)
                continue

            if hour >= half_day_hour and hour < self.settings.MARKET_CLOSE_HOUR:
                logger.info("≡ƒîô Yar─▒m g├╝n - sadece son saatlerde tarama yap─▒l─▒yor")
                self.scanner.scan_once()
                sleep(3600 * (self.settings.MARKET_CLOSE_HOUR - half_day_hour))
                continue

            try:
                self.scanner.scan_once()
            except Exception as e:
                logger.error(f"Γ¥î Tarama hatas─▒: {e}")
                self.notifier.send_message(f"ΓÜá∩╕Å Bot hatas─▒: {e}")

            logger.info(f"\nΓÅ│ Sonraki tarama: {self.settings.SCAN_INTERVAL_MINUTES} dakika sonra")

            for _ in range(self.settings.SCAN_INTERVAL_MINUTES * 6):
                if not self.running:
                    break
                sleep(10)

        logger.info("≡ƒæï Bot durduruldu.")
