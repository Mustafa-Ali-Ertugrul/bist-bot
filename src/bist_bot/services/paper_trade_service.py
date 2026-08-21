"""Paper trade persistence and lifecycle update helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import TR, bist_close_time, is_bist_holiday
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
        # Faz 3 P2: in-memory trailing extremes (ticker -> max price for long,
        # min price for short). Restart-safe degradation: on restart the map is
        # empty and the original stop applies until prices re-ratchet it.
        self._trail_extremes: dict[str, float] = {}

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

    def update_open_trades(
        self, signals: list[Signal] | None = None, *, now: datetime | None = None
    ) -> None:
        """Lifecycle update with direction-aware stop/target checks.

        Long:  stop hits when price <= stop, target when price >= target.
        Short: stop hits when price >= stop, target when price <= target.
        When both levels are crossed by the same price the stop wins (conservative,
        matching the backtest measurement contract).

        Close priority: OPPOSITE_SIGNAL > STOP_HIT > TRAIL_STOP_HIT > TARGET_HIT
        > EOD_CLOSE.

        Faz 3 P1 (EOD discipline): after ``bist_close_time(date)`` (17:30 full
        day, 12:30 half-day, holidays excluded) every still-open paper position
        closes with reason ``EOD_CLOSE`` — same contract as
        ``SignalOutcomeTracker._is_eod``. ``now`` is injectable for tests;
        defaults to ``datetime.now(UTC)``.

        Faz 3 P2 (trailing stop): when ``TRAILING_STOP_ENABLED`` is true, an
        in-memory extreme (high-water for long / low-water for short, seeded at
        entry price) ratchets a trail at ``TRAILING_STOP_PCT`` percent. The
        trail only ever tightens the original stop; crossing it closes with
        ``TRAIL_STOP_HIT``. In-memory by design: restart degrades safely to the
        original stop.

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

        effective_now = now or datetime.now(UTC)
        trail_enabled = bool(getattr(self.settings, "TRAILING_STOP_ENABLED", False))
        try:
            trail_pct = float(getattr(self.settings, "TRAILING_STOP_PCT", 2.0))
        except (TypeError, ValueError):
            trail_pct = 2.0

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
                self._trail_extremes.pop(trade.ticker, None)
                continue

            # === Faz 3 P2: trailing stop extreme ratchet (in-memory) ===
            trail_stop: float | None = None
            if trail_enabled and trail_pct > 0:
                seeded = self._trail_extremes.get(trade.ticker)
                if seeded is None:
                    seeded = trade.signal_price
                if direction == "short":
                    extreme = min(seeded, current)
                    trail_stop = extreme * (1 + trail_pct / 100.0)
                else:
                    extreme = max(seeded, current)
                    trail_stop = extreme * (1 - trail_pct / 100.0)
                self._trail_extremes[trade.ticker] = extreme

            if direction == "short":
                stop_hit = trade.stop_loss and current >= trade.stop_loss
                target_hit = trade.target_price and current <= trade.target_price
                # Trail only classifies as TRAIL when it is tighter than the
                # original stop; otherwise the original STOP_HIT contract wins.
                trail_hit = (
                    trail_stop is not None
                    and (not trade.stop_loss or trail_stop < trade.stop_loss)
                    and current >= trail_stop
                )
            else:
                stop_hit = trade.stop_loss and current <= trade.stop_loss
                target_hit = trade.target_price and current >= trade.target_price
                trail_hit = (
                    trail_stop is not None
                    and (not trade.stop_loss or trail_stop > trade.stop_loss)
                    and current <= trail_stop
                )

            closed = False
            if stop_hit:
                self._close_trade(trade, current, "STOP_HIT", direction)
                closed = True
            elif trail_hit:
                self._close_trade(trade, current, "TRAIL_STOP_HIT", direction)
                closed = True
            elif target_hit:
                self._close_trade(trade, current, "TARGET_HIT", direction)
                closed = True
            elif self._is_eod(effective_now):
                # === Faz 3 P1: EOD discipline — no intraday position survives
                # the session; mirrors SignalOutcomeTracker's EOD contract.
                self._close_trade(trade, current, "EOD_CLOSE", direction)
                closed = True

            if closed:
                self._trail_extremes.pop(trade.ticker, None)

        logger.info("paper_trade_update_completed", ticker_count=len(prices))

    def _is_eod(self, now: datetime) -> bool:
        """Session-end check — identical contract to SignalOutcomeTracker._is_eod.

        Uses market_calendar.bist_close_time (half-day aware) and excludes
        holidays/weekends. Any error degrades to "not EOD" (fail-open keeps the
        position under its normal stop/target contract).
        """
        try:
            local_now = now.astimezone(TR)
            d = local_now.date()
            if is_bist_holiday(d):
                return False
            return local_now.time() >= bist_close_time(d)
        except Exception:
            return False

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
            "TRAIL_STOP_HIT": "paper_trade_trail_stop_hit",
            "EOD_CLOSE": "paper_trade_eod_close",
        }.get(reason, "paper_trade_closed")
        logger.info(
            event,
            ticker=trade.ticker,
            current_price=round(current, 2),
            direction=direction,
            actual_profit_pct=profit_pct,
        )
