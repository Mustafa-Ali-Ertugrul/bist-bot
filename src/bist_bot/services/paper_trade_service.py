"""Paper trade persistence and lifecycle update helpers."""

from __future__ import annotations

from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.strategy.regime import detect_regime

logger = get_logger(__name__, component="paper_trade")


class PaperTradeService:
    def __init__(self, fetcher, db, settings: Any | None = None) -> None:
        self.fetcher = fetcher
        self.db = db
        self.settings = settings or default_settings

    def queue_actionable_signals(self, signals) -> None:
        if not getattr(self.settings, "PAPER_MODE", False):
            return

        for signal in signals:
            regime_frame = self.fetcher.fetch_single(signal.ticker, period="3mo")
            regime_enum = detect_regime(regime_frame)
            regime = regime_enum.value if regime_enum else "UNKNOWN"
            self.db.add_paper_trade(
                ticker=signal.ticker,
                signal_type=signal.signal_type.value,
                signal_price=signal.price,
                signal_time=signal.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                stop_loss=signal.stop_loss,
                target_price=signal.target_price,
                score=int(signal.score),
                regime=regime,
            )

    def update_open_trades(self) -> None:
        if not getattr(self.settings, "PAPER_MODE", False):
            return

        open_trades = self.db.get_open_paper_trades()
        if not open_trades:
            return

        prices: dict[str, float] = {}
        for trade in open_trades:
            df = self.fetcher.fetch_single(trade.ticker, period="1d")
            if df is not None:
                prices[trade.ticker] = float(df["close"].iloc[-1])

        if not prices:
            return

        self.db.update_all_paper_close(prices)
        for trade in open_trades:
            current = prices.get(trade.ticker)
            if current is None:
                continue
            if trade.stop_loss and current <= trade.stop_loss:
                self.db.close_paper_trade(trade.id, current, "STOP_HIT")
                logger.info(
                    "paper_trade_stop_hit",
                    ticker=trade.ticker,
                    current_price=round(current, 2),
                )
            elif trade.target_price and current >= trade.target_price:
                self.db.close_paper_trade(trade.id, current, "TARGET_HIT")
                logger.info(
                    "paper_trade_target_hit",
                    ticker=trade.ticker,
                    current_price=round(current, 2),
                )

        logger.info("paper_trade_update_completed", ticker_count=len(prices))
