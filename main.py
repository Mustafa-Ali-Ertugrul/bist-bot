import sys
import signal
import logging
import io
from datetime import datetime
from time import sleep
from threading import Thread

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import config
from data_fetcher import BISTDataFetcher
from strategy import StrategyEngine, SignalType, Signal
from notifier import TelegramNotifier
from database import SignalDatabase
from backtest import Backtester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


class BISTBot:
    def __init__(self):
        self.fetcher = BISTDataFetcher()
        self.engine = StrategyEngine()
        self.notifier = TelegramNotifier()
        self.db = SignalDatabase()
        self.running = False

        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("\n🛑 Bot durduruluyor...")
        self.running = False

    def _check_signal_changes(self, signals: list):
        for s in signals:
            prev = self.db.get_latest_signal(s.ticker)
            if prev and prev["signal_type"] != s.signal_type.value:
                from datetime import datetime as dt
                
                old_signal = Signal(
                    ticker=prev["ticker"],
                    signal_type=SignalType(prev["signal_type"]),
                    score=prev["score"],
                    price=prev["price"],
                    stop_loss=prev.get("stop_loss", 0) or 0,
                    target_price=prev.get("target_price", 0) or 0,
                    confidence=prev.get("confidence", "DÜŞÜK") or "DÜŞÜK",
                    timestamp=dt.fromisoformat(prev["timestamp"]),
                )
                
                self.notifier.send_signal_change(
                    s.ticker, old_signal, s
                )
                logger.info(
                    f"🔔 Sinyal değişikliği: {s.ticker} "
                    f"{prev['signal_type']} → {s.signal_type.value}"
                )
                sleep(1)

    def scan_once(self) -> list:
        logger.info("\n" + "█" * 55)
        logger.info("█  BIST BOT — TARAMA BAŞLIYOR")
        logger.info(f"█  Saat: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        logger.info(f"█  Watchlist: {len(config.WATCHLIST)} hisse")
        logger.info("█" * 55)

        self.fetcher.clear_cache()
        all_data = self.fetcher.fetch_all()

        if not all_data:
            logger.error("❌ Hiçbir veri çekilemedi!")
            return []

        logger.info("\n🧠 Strateji analizi yapılıyor...")
        signals = self.engine.scan_all(all_data)

        actionable = self.engine.get_actionable_signals(signals)

        buys = [s for s in signals if s.score > 0]
        sells = [s for s in signals if s.score < 0]

        logger.info(f"\n{'─'*55}")
        logger.info(f"📊 SONUÇLAR:")
        logger.info(f"  Taranan: {len(all_data)} hisse")
        logger.info(f"  Alım sinyali: {len(buys)}")
        logger.info(f"  Satış sinyali: {len(sells)}")
        logger.info(f"  Aksiyon gerekli: {len(actionable)}")
        logger.info(f"{'─'*55}")

        for s in signals:
            if s.signal_type not in (SignalType.HOLD,):
                print(s)

        self._check_signal_changes(signals)

        for s in actionable:
            self.db.save_signal(s)

        self.db.save_scan_log(
            len(all_data), len(actionable),
            len(buys), len(sells)
        )

        if actionable:
            self.notifier.send_scan_summary(signals, len(all_data))

            strong = [
                s for s in actionable
                if abs(s.score) >= 35
            ]
            for s in strong:
                self.notifier.send_signal(s)
                sleep(1)

        return signals

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

            if hour < config.MARKET_OPEN_HOUR:
                wait = (config.MARKET_OPEN_HOUR - hour) * 3600
                logger.info(
                    f"⏰ Borsa henüz açılmadı. "
                    f"{config.MARKET_OPEN_HOUR}:00'da başlayacak..."
                )
                sleep(min(wait, 1800))
                continue

            warmup_minutes = getattr(config, "MARKET_WARMUP_MINUTES", 15)
            half_day_hour = getattr(config, "MARKET_HALF_DAY_HOUR", 13)
            
            if hour >= config.MARKET_CLOSE_HOUR:
                logger.info("🌙 Borsa kapandı. Yarın görüşürüz!")
                self.scan_once()
                sleep(3600 * 14)
                continue
            
            if hour == config.MARKET_OPEN_HOUR and minute < warmup_minutes:
                logger.info(f"🌅 Açılış gürültüsü - ilk {warmup_minutes} dakika bekleniyor...")
                sleep(60)
                continue
                
            if hour >= half_day_hour and hour < config.MARKET_CLOSE_HOUR:
                logger.info("🌓 Yarım gün - sadece son saatlerde tarama yapılıyor")
                self.scan_once()
                sleep(3600 * (config.MARKET_CLOSE_HOUR - half_day_hour))
                continue

            try:
                self.scan_once()
            except Exception as e:
                logger.error(f"❌ Tarama hatası: {e}")
                self.notifier.send_message(f"⚠️ Bot hatası: {e}")

            logger.info(
                f"\n⏳ Sonraki tarama: "
                f"{config.SCAN_INTERVAL_MINUTES} dakika sonra"
            )

            for _ in range(config.SCAN_INTERVAL_MINUTES * 6):
                if not self.running:
                    break
                sleep(10)

        logger.info("👋 Bot durduruldu.")

    def run_backtest(self):
        logger.info("\n🧪 BACKTEST BAŞLIYOR")
        logger.info("=" * 55)

        backtester = Backtester(initial_capital=8500)
        results = []

        for ticker in config.WATCHLIST:
            df = self.fetcher.fetch_single(ticker, period="1y")
            if df is not None:
                result = backtester.run(ticker, df, verbose=False)
                if result:
                    results.append(result)
                    print(result)

        if results:
            avg_return = sum(r.total_return_pct for r in results) / len(results)
            avg_winrate = sum(r.win_rate for r in results) / len(results)
            total_trades = sum(r.total_trades for r in results)

            print(f"\n{'═'*55}")
            print(f"📊 GENEL BACKTEST ÖZETİ")
            print(f"{'═'*55}")
            print(f"  Test edilen : {len(results)} hisse")
            print(f"  Toplam işlem: {total_trades}")
            print(f"  Ort. getiri : %{avg_return:.2f}")
            print(f"  Ort. win rate: %{avg_winrate:.1f}")

            best = max(results, key=lambda r: r.total_return_pct)
            worst = min(results, key=lambda r: r.total_return_pct)
            print(f"  En iyi      : {best.ticker} (%{best.total_return_pct:+.2f})")
            print(f"  En kötü     : {worst.ticker} (%{worst.total_return_pct:+.2f})")
            print(f"{'═'*55}")


def main():
    bot = BISTBot()

    if "--once" in sys.argv:
        bot.scan_once()

    elif "--backtest" in sys.argv:
        bot.run_backtest()

    elif "--dashboard" in sys.argv:
        from dashboard import app
        logger.info(f"🌐 Dashboard: http://localhost:{config.FLASK_PORT}")
        app.run(
            host="0.0.0.0",
            port=config.FLASK_PORT,
            debug=config.FLASK_DEBUG
        )

    else:
        from dashboard import app

        dashboard_thread = Thread(
            target=lambda: app.run(
                host="0.0.0.0",
                port=config.FLASK_PORT,
                debug=False,
                use_reloader=False
            ),
            daemon=True
        )
        dashboard_thread.start()
        logger.info(f"🌐 Dashboard: http://localhost:{config.FLASK_PORT}")

        bot.run_loop()


if __name__ == "__main__":
    main()
