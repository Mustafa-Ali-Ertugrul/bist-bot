import sys
import signal
import logging
import io
from datetime import datetime
from time import sleep
from threading import Thread

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from config import settings
from contracts import DataFetcherProtocol, NotifierProtocol, SignalRepositoryProtocol, StrategyEngineProtocol
from dashboard import create_dashboard_app
from dependencies import build_app_container
from signal_models import Signal, SignalType
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
    def __init__(
        self,
        fetcher: DataFetcherProtocol,
        engine: StrategyEngineProtocol,
        notifier: NotifierProtocol,
        db: SignalRepositoryProtocol,
        paper_trade_fetcher: DataFetcherProtocol | None = None,
        backtester_factory=None,
    ):
        self.fetcher = fetcher
        self.engine = engine
        self.notifier = notifier
        self.db = db
        self.paper_trade_fetcher = paper_trade_fetcher or fetcher
        self.backtester_factory = backtester_factory or (
            lambda: Backtester(initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0))
        )
        self.running = False

        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("\n🛑 Bot durduruluyor...")
        self.running = False

    def _check_signal_changes(self, signals: list):
        for s in signals:
            prev = self.db.get_latest_signal(s.ticker)
            if prev and prev["signal_type"] != s.signal_type.value:
                old_signal = Signal(
                    ticker=prev["ticker"],
                    signal_type=SignalType(prev["signal_type"]),
                    score=prev["score"],
                    price=prev["price"],
                    stop_loss=prev.get("stop_loss", 0) or 0,
                    target_price=prev.get("target_price", 0) or 0,
                    confidence=prev.get("confidence", "DÜŞÜK") or "DÜŞÜK",
                    timestamp=datetime.fromisoformat(prev["timestamp"]),
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
        logger.info(f"█  Watchlist: {len(settings.WATCHLIST)} hisse")
        logger.info("█" * 55)

        self.fetcher.clear_cache()
        all_data = self.fetcher.fetch_multi_timeframe_all(
            trend_period=getattr(settings, "MTF_TREND_PERIOD", "6mo"),
            trend_interval=getattr(settings, "MTF_TREND_INTERVAL", "1d"),
            trigger_period=getattr(settings, "MTF_TRIGGER_PERIOD", "1mo"),
            trigger_interval=getattr(settings, "MTF_TRIGGER_INTERVAL", "15m"),
        )

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
            
            if getattr(settings, "PAPER_MODE", False):
                from strategy import detect_regime, MarketRegime
                regime_enum = detect_regime(self.fetcher.fetch_single(s.ticker, period="3mo"))
                regime = regime_enum.value if regime_enum else "UNKNOWN"
                self.db.add_paper_trade(
                    ticker=s.ticker,
                    signal_type=s.signal_type.value,
                    signal_price=s.price,
                    signal_time=s.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    score=int(s.score),
                    regime=regime,
                )

        self.db.save_scan_log(
            len(all_data), len(actionable),
            len(buys), len(sells)
        )

        if actionable:
            self.notifier.send_scan_summary(signals, len(all_data))

            strong = [
                s for s in actionable
                if abs(s.score) >= getattr(settings, "TELEGRAM_MIN_SCORE", 70)
            ]
            for s in strong:
                self.notifier.send_signal(s)
                sleep(1)

        if getattr(settings, "PAPER_MODE", False):
            self.update_paper_trades()

        return signals

    def update_paper_trades(self):
        if not getattr(settings, "PAPER_MODE", False):
            return

        open_trades = self.db.get_open_paper_trades()
        if not open_trades:
            return

        prices = {}
        for trade in open_trades:
            ticker = trade[1]
            df = self.fetcher.fetch_single(ticker, period="1d")
            if df is not None:
                prices[ticker] = float(df["close"].iloc[-1])
        
        if prices:
            self.db.update_all_paper_close(prices)
            logger.info(f"  📊 Paper trade güncellendi: {len(prices)} hisse")

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

            if hour < settings.MARKET_OPEN_HOUR:
                wait = (settings.MARKET_OPEN_HOUR - hour) * 3600
                logger.info(
                    f"⏰ Borsa henüz açılmadı. "
                    f"{settings.MARKET_OPEN_HOUR}:00'da başlayacak..."
                )
                sleep(min(wait, 1800))
                continue

            warmup_minutes = getattr(settings, "MARKET_WARMUP_MINUTES", 15)
            half_day_hour = getattr(settings, "MARKET_HALF_DAY_HOUR", 13)
            
            if hour >= settings.MARKET_CLOSE_HOUR:
                logger.info("🌙 Borsa kapandı. Yarın görüşürüz!")
                self.scan_once()
                sleep(3600 * 14)
                continue
            
            if hour == settings.MARKET_OPEN_HOUR and minute < warmup_minutes:
                logger.info(f"🌅 Açılış gürültüsü - ilk {warmup_minutes} dakika bekleniyor...")
                sleep(60)
                continue
                
            if hour >= half_day_hour and hour < settings.MARKET_CLOSE_HOUR:
                logger.info("🌓 Yarım gün - sadece son saatlerde tarama yapılıyor")
                self.scan_once()
                sleep(3600 * (settings.MARKET_CLOSE_HOUR - half_day_hour))
                continue

            try:
                self.scan_once()
            except Exception as e:
                logger.error(f"❌ Tarama hatası: {e}")
                self.notifier.send_message(f"⚠️ Bot hatası: {e}")

            logger.info(
                f"\n⏳ Sonraki tarama: "
                f"{settings.SCAN_INTERVAL_MINUTES} dakika sonra"
            )

            for _ in range(settings.SCAN_INTERVAL_MINUTES * 6):
                if not self.running:
                    break
                sleep(10)

        logger.info("👋 Bot durduruldu.")

    def run_backtest(self):
        logger.info("\n🧪 BACKTEST BAŞLIYOR")
        logger.info("=" * 55)

        backtester = self.backtester_factory()
        results = []

        for ticker in settings.WATCHLIST:
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
    container = build_app_container()
    bot = BISTBot(
        fetcher=container.fetcher,
        engine=container.engine,
        notifier=container.notifier,
        db=container.db,
        paper_trade_fetcher=container.paper_trade_fetcher,
        backtester_factory=container.backtester_factory,
    )
    dashboard_app = create_dashboard_app(
        fetcher=container.fetcher,
        engine=container.engine,
        db=container.db,
    )

    if "--once" in sys.argv:
        bot.scan_once()

    elif "--backtest" in sys.argv:
        bot.run_backtest()

    elif "--dashboard" in sys.argv:
        logger.info(f"🌐 Dashboard: http://localhost:{settings.FLASK_PORT}")
        dashboard_app.run(
            host="0.0.0.0",
            port=settings.FLASK_PORT,
            debug=settings.FLASK_DEBUG
        )

    else:
        dashboard_thread = Thread(
            target=lambda: dashboard_app.run(
                host="0.0.0.0",
                port=settings.FLASK_PORT,
                debug=False,
                use_reloader=False
            ),
            daemon=True
        )
        dashboard_thread.start()
        logger.info(f"🌐 Dashboard: http://localhost:{settings.FLASK_PORT}")

        bot.run_loop()


if __name__ == "__main__":
    main()
