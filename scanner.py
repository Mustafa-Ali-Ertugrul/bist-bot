import logging
import config
from datetime import datetime
from time import sleep

from strategy import SignalType, Signal, detect_regime


logger = logging.getLogger(__name__)


class ScanService:
    def __init__(self, fetcher, engine, notifier, db):
        self.fetcher = fetcher
        self.engine = engine
        self.notifier = notifier
        self.db = db

    def _check_signal_changes(self, signals):
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
        logger.info(f"█  Watchlist: {len(config.settings.WATCHLIST)} hisse")
        logger.info("█" * 55)

        self.fetcher.clear_cache()
        all_data = self.fetcher.fetch_multi_timeframe_all(
            trend_period=getattr(config.settings, "MTF_TREND_PERIOD", "6mo"),
            trend_interval=getattr(config.settings, "MTF_TREND_INTERVAL", "1d"),
            trigger_period=getattr(config.settings, "MTF_TRIGGER_PERIOD", "1mo"),
            trigger_interval=getattr(config.settings, "MTF_TRIGGER_INTERVAL", "15m"),
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
        logger.info("📊 SONUÇLAR:")
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

            if getattr(config.settings, "PAPER_MODE", False):
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
                if abs(s.score) >= getattr(config.settings, "TELEGRAM_MIN_SCORE", 70)
            ]
            for s in strong:
                self.notifier.send_signal(s)
                sleep(1)

        if getattr(config.settings, "PAPER_MODE", False):
            self.update_paper_trades()

        return signals

    def update_paper_trades(self):
        if not getattr(config.settings, "PAPER_MODE", False):
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
