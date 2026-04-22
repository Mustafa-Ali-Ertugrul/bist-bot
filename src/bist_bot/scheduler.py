"""Market-hours scheduler for the CLI bot runtime."""

import logging
from datetime import datetime
from time import sleep

from bist_bot.config.settings import settings as default_settings


logger = logging.getLogger(__name__)


class MarketScheduler:
    def __init__(self, scan_service, notifier, settings=default_settings):
        self.scanner = scan_service
        self.notifier = notifier
        self.settings = settings
        self.running = False

    def run_loop(self):
        self.running = True

        logger.info("🚀 BIST Bot başlatılıyor...")
        self.notifier.send_startup_message()

        while self.running:
            now = datetime.now()
            hour = now.hour
            minute = now.minute

            weekday = now.weekday()

            if weekday >= 5:
                logger.info("📅 Hafta sonu — tarama yapılmıyor")
                sleep(3600)
                continue

            if hour < self.settings.MARKET_OPEN_HOUR:
                wait = (self.settings.MARKET_OPEN_HOUR - hour) * 3600
                logger.info(
                    f"⏰ Borsa henüz açılmadı. "
                    f"{self.settings.MARKET_OPEN_HOUR}:00'da başlayacak..."
                )
                sleep(min(wait, 1800))
                continue

            warmup_minutes = getattr(self.settings, "MARKET_WARMUP_MINUTES", 15)
            half_day_hour = getattr(self.settings, "MARKET_HALF_DAY_HOUR", 13)

            if hour >= self.settings.MARKET_CLOSE_HOUR:
                logger.info("🌙 Borsa kapandı. Yarın görüşürüz!")
                self.scanner.scan_once()
                sleep(3600 * 14)
                continue

            if hour == self.settings.MARKET_OPEN_HOUR and minute < warmup_minutes:
                logger.info(f"🌅 Açılış gürültüsü - ilk {warmup_minutes} dakika bekleniyor...")
                sleep(60)
                continue

            if hour >= half_day_hour and hour < self.settings.MARKET_CLOSE_HOUR:
                logger.info("🌓 Yarım gün - sadece son saatlerde tarama yapılıyor")
                self.scanner.scan_once()
                sleep(3600 * (self.settings.MARKET_CLOSE_HOUR - half_day_hour))
                continue

            try:
                self.scanner.scan_once()
            except Exception as e:
                logger.error(f"❌ Tarama hatası: {e}")
                self.notifier.send_message(f"⚠️ Bot hatası: {e}")

            logger.info(
                f"\n⏳ Sonraki tarama: "
                f"{self.settings.SCAN_INTERVAL_MINUTES} dakika sonra"
            )

            CHECK_INTERVAL_SECONDS = 10
            total_wait_seconds = self.settings.SCAN_INTERVAL_MINUTES * 60
            max_iterations = total_wait_seconds // CHECK_INTERVAL_SECONDS
            for _ in range(max_iterations):
                if not self.running:
                    break
                sleep(CHECK_INTERVAL_SECONDS)

        logger.info("👋 Bot durduruldu.")