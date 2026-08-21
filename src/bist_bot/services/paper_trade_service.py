"""Paper trade persistence and lifecycle update helpers."""

from __future__ import annotations

from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.strategy.regime import detect_regime
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="paper_trade")


def paper_direction_from_signal_type(signal_type: str) -> str:
    """Map a persisted signal type string to the paper trade position direction."""
    try:
        parsed = SignalType(signal_type)
    except ValueError:
        return "long"
    return "short" if parsed.is_sell else "long"


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
        direction: str = "long",
    ) -> float:
        """Direction-aware net PnL percentage (fees included).

        Long:  PnL = (exit - entry) / entry,  fees = buy(entry) + sell(exit)
        Short: PnL = (entry - exit) / entry,  fees = sell(entry) + buy(exit)
        """
        from bist_bot.risk.costs import DEFAULT_COSTS, TradingCosts

        trading_costs: TradingCosts = costs if isinstance(costs, TradingCosts) else DEFAULT_COSTS
        if entry_price <= 0:
            return 0.0
        if direction == "short":
            total_fees = trading_costs.round_trip_cost(exit_price, entry_price)
            gross_pct = (entry_price - exit_price) / entry_price * 100
        else:
            total_fees = trading_costs.round_trip_cost(entry_price, exit_price)
            gross_pct = (exit_price - entry_price) / entry_price * 100
        fee_pct = total_fees / entry_price * 100
        return round(gross_pct - fee_pct, 4)

    def _is_in_paper_cooldown(self, ticker: str) -> bool:
        """Check if ticker has been recently closed in paper trade (cooldown period)."""
        cooldown_days = int(getattr(self.settings, "PAPER_COOLDOWN_DAYS", 5))
        if cooldown_days <= 0:
            return False
        try:
            recent = self.db.get_recent_closed_trades(ticker, days=cooldown_days)
            return len(recent) > 0
        except Exception:
            return False

    def queue_actionable_signals(self, signals) -> bool:
        if not getattr(self.settings, "PAPER_MODE", False):
            return False

        for signal in signals:
            # === Faz 3: cooldown kontrolü ===
            if self._is_in_paper_cooldown(signal.ticker):
                logger.info(
                    "paper_trade_cooldown",
                    ticker=signal.ticker,
                    reason="recently closed within cooldown window",
                )
                continue

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
            direction = "short" if signal.signal_type.is_sell else "long"
            self.db.add_paper_trade(
                ticker=signal.ticker,
                signal_type=signal.signal_type.value,
                signal_price=signal.price,
                signal_time=signal.timestamp,
                stop_loss=signal.stop_loss,
                target_price=signal.target_price,
                score=int(signal.score),
                regime=regime,
                direction=direction,
            )
        return True

    @staticmethod
    def _trade_direction(trade: Any) -> str:
        """Resolve position direction: persisted column first, signal type for legacy rows."""
        direction = getattr(trade, "direction", None)
        if direction in ("long", "short"):
            return direction
        return paper_direction_from_signal_type(getattr(trade, "signal_type", ""))

    def update_open_trades(self, signals: list[Signal] | None = None) -> None:
        """Lifecycle update with direction-aware stop/target checks.

        Long:  stop hits when price <= stop, target when price >= target.
        Short: stop hits when price >= stop, target when price <= target.
        When both levels are crossed by the same price the stop wins (conservative,
        matching the backtest measurement contract).

        Price-source contract (single source of truth):
        current scan ``signals`` are the primary price source (zero-latency);
        only tickers missing from the scan are fetched via ``fetcher.fetch_all``.
        When ``signals`` is None/empty the fetch fallback is used for all tickers
        (result identical, only optimization skipped).
        """
        if not getattr(self.settings, "PAPER_MODE", False):
            return

        open_trades = self.db.get_open_paper_trades()
        if not open_trades:
            return

        unique_tickers = list({trade.ticker for trade in open_trades})
        unique_set = set(unique_tickers)

        # Primary price source: scan signals (zero-latency); build lookup for
        # opposite-signal check at the same time.
        signal_lookup: dict[str, Signal] = {}
        prices: dict[str, float] = {}
        if signals:
            for sig in signals:
                signal_lookup[sig.ticker] = sig
                if sig.ticker in unique_set:
                    try:
                        prices[sig.ticker] = float(sig.price)
                    except (TypeError, ValueError):
                        pass

        # Fetch only missing tickers (fallback). Documented fallback: if
        # test_broker_paper mocks fetch_all, the result is unchanged — only the
        # optimization is skipped when signals are absent.
        missing = [t for t in unique_tickers if t not in prices]
        if missing:
            try:
                batch = self.fetcher.fetch_all(period="1d", force=False) or {}
            except Exception:
                batch = {}
            for ticker in missing:
                df = batch.get(ticker)
                if df is not None and len(df) > 0 and "close" in df.columns:
                    try:
                        prices[ticker] = float(df["close"].iloc[-1])
                    except (TypeError, ValueError, KeyError, IndexError):
                        pass

        if not prices:
            return

        for trade in open_trades:
            current = prices.get(trade.ticker)
            if current is None:
                continue

            direction = self._trade_direction(trade)

            # === Faz 3: Opposite_signal kapanışı (direction-aware) ===
            opposite_signal = False
            if trade.ticker in signal_lookup:
                sig = signal_lookup[trade.ticker]
                if direction == "short":
                    opposite = sig.signal_type.is_buy
                else:
                    opposite = sig.signal_type.is_sell
                # Only close on strong enough opposite signal
                if opposite and abs(sig.score) >= 15:
                    opposite_signal = True

            if opposite_signal:
                self._close_trade(trade, current, "OPPOSITE_SIGNAL", direction)
                continue

            if direction == "short":
                stop_hit = trade.stop_loss and current >= trade.stop_loss
                target_hit = trade.target_price and current <= trade.target_price
            else:
                stop_hit = trade.stop_loss and current <= trade.stop_loss
                target_hit = trade.target_price and current >= trade.target_price

            if stop_hit:
                self._close_trade(trade, current, "STOP_HIT", direction)
            elif target_hit:
                self._close_trade(trade, current, "TARGET_HIT", direction)

        logger.info("paper_trade_update_completed", ticker_count=len(prices))

    def _close_trade(self, trade: Any, current: float, reason: str, direction: str) -> None:
        """Close a paper trade with direction-aware net PnL recorded."""
        profit_pct = self.net_profit_pct(trade.signal_price, current, self.costs, direction)
        self.db.close_paper_trade(
            trade.ticker,
            current,
            reason,
            actual_profit_pct=profit_pct,
        )
        event = {
            "STOP_HIT": "paper_trade_stop_hit",
            "TARGET_HIT": "paper_trade_target_hit",
            "OPPOSITE_SIGNAL": "paper_trade_opposite_signal_exit",
        }.get(reason, "paper_trade_closed")
        logger.info(
            event,
            ticker=trade.ticker,
            current_price=round(current, 2),
            direction=direction,
            actual_profit_pct=profit_pct,
        )
