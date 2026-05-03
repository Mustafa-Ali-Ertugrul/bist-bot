"""Paper trade persistence and lifecycle update helpers."""

from __future__ import annotations

from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.strategy.regime import detect_regime

logger = get_logger(__name__, component="paper_trade")


class PaperTradeService:
    def __init__(self, fetcher, db, settings: Any | None = None, costs: Any | None = None) -> None:
        self.fetcher = fetcher
        self.db = db
        self.settings = settings or default_settings
        self.costs = costs

    @staticmethod
    def net_profit_pct(
        entry_price: float,
        exit_price: float,
        costs: Any | None = None,
    ) -> float:
        from bist_bot.risk.costs import DEFAULT_COSTS, TradingCosts

        trading_costs: TradingCosts = costs if isinstance(costs, TradingCosts) else DEFAULT_COSTS
        if entry_price <= 0:
            return 0.0
        buy_notional = entry_price
        sell_notional = exit_price
        total_fees = trading_costs.round_trip_cost(buy_notional, sell_notional)
        gross_pct = (exit_price - entry_price) / entry_price * 100
        fee_pct = total_fees / entry_price * 100
        return round(gross_pct - fee_pct, 4)

    def queue_actionable_signals(self, signals) -> bool:
        if not getattr(self.settings, "PAPER_MODE", False):
            return False

        for signal in signals:
            regime_frame = self.fetcher.fetch_single(signal.ticker, period="3mo")
            fetch_meta_getter = getattr(self.fetcher, "get_last_history_fetch_meta", None)
            fetch_meta_raw = (
                fetch_meta_getter(
                    signal.ticker, "3mo", getattr(self.settings, "DATA_INTERVAL", "1d")
                )
                if callable(fetch_meta_getter)
                else None
            )
            fetch_meta = fetch_meta_raw if isinstance(fetch_meta_raw, dict) else {}
            if regime_frame is None:
                logger.warning(
                    "paper_trade_regime_data_unavailable",
                    ticker=signal.ticker,
                    fetch_source=fetch_meta.get("source", "unknown"),
                    fetch_status=fetch_meta.get("status", "unknown"),
                    fetch_reason=fetch_meta.get("reason"),
                )
            regime_enum = detect_regime(regime_frame)
            regime = regime_enum.value if regime_enum else "UNKNOWN"
            if regime == "UNKNOWN":
                logger.info(
                    "paper_trade_regime_unknown",
                    ticker=signal.ticker,
                    fetch_source=fetch_meta.get("source", "unknown"),
                    fetch_status=fetch_meta.get("status", "unknown"),
                    fetch_reason=fetch_meta.get("reason"),
                    has_frame=regime_frame is not None,
                    candle_count=len(regime_frame) if regime_frame is not None else 0,
                )
            self.db.add_paper_trade(
                ticker=signal.ticker,
                signal_type=signal.signal_type.value,
                signal_price=signal.price,
                signal_time=signal.timestamp,
                stop_loss=signal.stop_loss,
                target_price=signal.target_price,
                score=int(signal.score),
                regime=regime,
            )
        return True

    def update_open_trades(self) -> None:
        if not getattr(self.settings, "PAPER_MODE", False):
            return

        open_trades = self.db.get_open_paper_trades()
        if not open_trades:
            return

        unique_tickers = list({trade.ticker for trade in open_trades})
        batch = self.fetcher.fetch_all(period="1d", force=False)

        prices: dict[str, float] = {}
        for ticker in unique_tickers:
            df = batch.get(ticker)
            if df is not None and len(df) > 0:
                prices[ticker] = float(df["close"].iloc[-1])

        if not prices:
            return

        for trade in open_trades:
            current = prices.get(trade.ticker)
            if current is None:
                continue
            if trade.stop_loss and current <= trade.stop_loss:
                self.db.close_paper_trade(trade.ticker, current, "STOP_HIT")
                logger.info(
                    "paper_trade_stop_hit",
                    ticker=trade.ticker,
                    current_price=round(current, 2),
                )
            elif trade.target_price and current >= trade.target_price:
                self.db.close_paper_trade(trade.ticker, current, "TARGET_HIT")
                logger.info(
                    "paper_trade_target_hit",
                    ticker=trade.ticker,
                    current_price=round(current, 2),
                )

        logger.info("paper_trade_update_completed", ticker_count=len(prices))
