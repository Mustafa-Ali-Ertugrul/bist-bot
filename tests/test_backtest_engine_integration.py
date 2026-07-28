"""End-to-end integration / regression tests for ``Backtester``.

WARNING / UYARI
---------------
If you intentionally change backtest sizing (``max_position_cap_pct`` /
``position_fraction``), default buy/sell thresholds, cost/slippage defaults,
vectorized vs iterative path selection, or how stop/target fills are simulated,
you MUST consciously update the expected trade counts, returns, notional caps,
and consistency assertions in this file.

Bu dosya, strateji skorları + risk boyutlandırmasının tarihsel OHLCV üzerinde
birlikte çalıştığını ve pozisyonların ``MAX_POSITION_CAP_PCT`` sınırını
aşmadığını garanti eder.

Architecture notes (production code):
- ``Backtester.run`` requires >= 50 rows after indicator dropna.
- Default path is vectorized (``_run_vectorized``); iterative is opt-in.
- Base mode deploys capital via ``position_fraction`` (default 1.0). Cap is
  enforced by setting ``position_fraction = max_position_cap_pct / 100``.
- There is no first-class ``DAILY_LOSS_CAP_PCT`` gate inside ``Backtester``;
  day-level risk-off is modeled here the same way the live risk layer does:
  after a loss day, further entries are blocked until the next session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from bist_bot.backtest import Backtester
from bist_bot.backtest.models import BacktestResult, BacktestTrade
from bist_bot.config.settings import settings


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class IterativeBacktester(Backtester):
    def _use_vectorized_path(self) -> bool:
        return False


class ScriptedBacktester(Backtester):
    """Deterministic enter/exit/size decisions keyed by history length."""

    def __init__(
        self,
        scripted_signals: dict[int, dict[str, float | bool]],
        *,
        force_iterative: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("indicators", IdentityIndicators())
        super().__init__(**kwargs)
        self.scripted_signals = scripted_signals
        self._force_iterative = force_iterative

    def _use_vectorized_path(self) -> bool:
        if self._force_iterative:
            return False
        return super()._use_vectorized_path()

    def _build_signal_context(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
        _ = ticker
        return self.scripted_signals.get(
            len(history),
            {
                "enter": False,
                "exit": False,
                "score": 0.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
            },
        )


class DailyLossAwareBacktester(ScriptedBacktester):
    """Applies a daily-loss risk-off gate around scripted entries.

    Mirrors live ``RiskManager.daily_loss_limit_reached`` semantics for the
    backtest path: once realized PnL for a calendar day breaches
    ``-capital * daily_loss_cap_pct / 100``, further entries that day are
    suppressed.
    """

    def __init__(
        self,
        scripted_signals: dict[int, dict[str, float | bool]],
        *,
        daily_loss_cap_pct: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(scripted_signals, force_iterative=True, **kwargs)
        self.daily_loss_cap_pct = float(daily_loss_cap_pct)
        self.daily_realized_pnl = 0.0
        self._daily_pnl_date: datetime | None = None
        self.blocked_entry_dates: list[datetime] = []
        self.allowed_entry_dates: list[datetime] = []

    def _roll_day(self, day: datetime) -> None:
        day_key = day.date() if hasattr(day, "date") else day
        current = None if self._daily_pnl_date is None else self._daily_pnl_date.date()
        if current != day_key:
            self.daily_realized_pnl = 0.0
            self._daily_pnl_date = day if isinstance(day, datetime) else datetime.combine(day_key, datetime.min.time())

    def _daily_loss_limit_reached(self) -> bool:
        if self.daily_loss_cap_pct <= 0:
            return False
        return self.daily_realized_pnl <= -(self.initial_capital * self.daily_loss_cap_pct / 100.0)

    def _open_position(
        self,
        signal: dict[str, float | bool],
        fill_price: float,
        reference_price: float,
        entry_date: datetime,
        capital: float,
    ) -> dict[str, Any] | None:
        self._roll_day(entry_date)
        if self._daily_loss_limit_reached():
            self.blocked_entry_dates.append(entry_date)
            return None
        position = super()._open_position(signal, fill_price, reference_price, entry_date, capital)
        if position is not None:
            self.allowed_entry_dates.append(entry_date)
        return position

    def _close_position(
        self,
        capital: float,
        position: dict[str, Any],
        trades: list[BacktestTrade],
        ticker: str,
        exit_date: datetime,
        fill_price: float,
        reference_price: float,
        reason: str,
        verbose: bool,
    ) -> float:
        before = len(trades)
        new_capital = super()._close_position(
            capital,
            position,
            trades,
            ticker,
            exit_date,
            fill_price,
            reference_price,
            reason,
            verbose,
        )
        if len(trades) > before:
            trade = trades[-1]
            self._roll_day(trade.exit_date)
            self.daily_realized_pnl += float(trade.profit_tl)
        return float(new_capital)


def _ohlcv(
    *,
    n: int,
    close_fn,
    rsi: float = 50.0,
    sma_cross: str = "NONE",
    macd_cross: str = "NONE",
    bb_position: str = "MIDDLE",
) -> pd.DataFrame:
    dates = pd.date_range(datetime(2024, 1, 1), periods=n, freq="D")
    rows: list[dict[str, object]] = []
    for idx, date in enumerate(dates):
        close = float(close_fn(idx))
        rows.append(
            {
                "date": date,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close + 0.1,
                "volume": 10_000.0,
                "volume_sma_20": 10_000.0,
                "atr": 1.5,
                "rsi": rsi,
                "sma_cross": sma_cross,
                "macd_cross": macd_cross,
                "bb_position": bb_position,
                "sma_5": close + 0.5,
                "sma_20": close - 0.5,
                "ema_200": close - 5.0,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def rising_trend_frame(n: int = 120) -> pd.DataFrame:
    return _ohlcv(n=n, close_fn=lambda i: 100.0 + i * 0.5, rsi=28.0, sma_cross="GOLDEN_CROSS", macd_cross="BULLISH", bb_position="BELOW_LOWER")


def falling_trend_frame(n: int = 120) -> pd.DataFrame:
    return _ohlcv(n=n, close_fn=lambda i: 200.0 - i * 0.5, rsi=75.0, sma_cross="DEATH_CROSS", macd_cross="BEARISH", bb_position="ABOVE_UPPER")


def sideways_frame(n: int = 120) -> pd.DataFrame:
    return _ohlcv(n=n, close_fn=lambda _i: 100.0, rsi=50.0, sma_cross="NONE", macd_cross="NONE", bb_position="MIDDLE")


def cyclic_signal_frame(n: int = 220) -> pd.DataFrame:
    """Mixed regime frame similar to vectorized regression fixture."""
    dates = pd.date_range(datetime(2024, 1, 1), periods=n, freq="D")
    rows: list[dict[str, object]] = []
    for idx, date in enumerate(dates):
        phase = idx % 44
        base = 100.0 + idx * 0.35
        if phase < 8:
            rsi, sma_cross, macd_cross, bb = 24.0, ("GOLDEN_CROSS" if phase == 0 else "NONE"), "BULLISH", "BELOW_LOWER"
            sma_fast, sma_slow = base + 2.0, base - 1.5
        elif 22 <= phase < 30:
            rsi, sma_cross, macd_cross, bb = 78.0, ("DEATH_CROSS" if phase == 22 else "NONE"), "BEARISH", "ABOVE_UPPER"
            sma_fast, sma_slow = base - 2.0, base + 1.5
        else:
            rsi, sma_cross, macd_cross, bb = 50.0, "NONE", "NONE", "MIDDLE"
            sma_fast, sma_slow = base + 0.5, base
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 2.5,
                "low": base - 2.5,
                "close": base + 0.6,
                "volume": 10_000.0,
                "volume_sma_20": 10_000.0,
                "atr": 2.0,
                "rsi": rsi,
                "sma_cross": sma_cross,
                "macd_cross": macd_cross,
                "bb_position": bb,
                "sma_5": sma_fast,
                "sma_20": sma_slow,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def _assert_trades_respect_position_cap(
    result: BacktestResult,
    *,
    capital: float,
    cap_pct: float,
) -> None:
    max_notional = capital * (cap_pct / 100.0)
    for trade in result.trades:
        # entry_notional is shares * entry_price; allow 1-share rounding slack via price.
        assert trade.entry_notional_tl <= max_notional + trade.entry_price + 1e-6
        if trade.position_fraction is not None:
            assert trade.position_fraction <= (cap_pct / 100.0) + 1e-9


def _zero_cost_settings():
    return settings.override(
        SLIPPAGE_PCT=0.0,
        SLIPPAGE_PENALTY_RATIO=0.0,
        SLIPPAGE_MAX_CAP=0.02,
    )


# ---------------------------------------------------------------------------
# Profitable / losing / sideways scenarios
# ---------------------------------------------------------------------------


def test_profitable_trend_scripted_run_is_profitable_and_respects_cap() -> None:
    """Karlı trend: yükselen fiyat + controlled entry/exit → positive return, cap OK."""
    capital = 100_000.0
    cap_pct = 5.0
    fraction = cap_pct / 100.0
    script = {
        50: {
            "enter": True,
            "exit": False,
            "score": 40.0,
            "stop_loss": 50.0,
            "target_price": 10_000.0,
            "position_fraction": fraction,
        },
        100: {
            "enter": False,
            "exit": True,
            "score": -25.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        },
    }
    engine = ScriptedBacktester(
        script,
        initial_capital=capital,
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
        max_position_cap_pct=cap_pct,
    )
    with _zero_cost_settings():
        result = engine.run("UP.IS", rising_trend_frame(), verbose=False)

    assert result is not None
    assert result.total_trades >= 1
    assert result.total_return_pct > 0
    assert result.final_capital > result.initial_capital
    _assert_trades_respect_position_cap(result, capital=capital, cap_pct=cap_pct)
    assert result.trades[0].position_fraction == pytest.approx(fraction)


def test_losing_trend_stop_exits_are_non_profitable_and_respect_cap() -> None:
    """Zararlı trend: falling tape + tight stop → stop-out, notional still capped."""
    capital = 100_000.0
    cap_pct = 5.0
    fraction = cap_pct / 100.0
    script = {
        50: {
            "enter": True,
            "exit": False,
            "score": 40.0,
            "stop_loss": 174.0,  # open≈175 → stop hit same/next bars
            "target_price": 300.0,
            "position_fraction": fraction,
        },
    }
    engine = ScriptedBacktester(
        script,
        initial_capital=capital,
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
        max_position_cap_pct=cap_pct,
    )
    with _zero_cost_settings():
        result = engine.run("DN.IS", falling_trend_frame(), verbose=False)

    assert result is not None
    assert result.total_trades >= 1
    assert any(trade.profit_tl <= 0 for trade in result.trades)
    assert any(trade.exit_reason in {"STOP_LOSS", "STOP_GAP"} for trade in result.trades)
    _assert_trades_respect_position_cap(result, capital=capital, cap_pct=cap_pct)


def test_daily_loss_cap_blocks_further_entries_until_day_rolls() -> None:
    """DAILY_LOSS_CAP risk-off: after realized loss hits cap, same-day entries blocked.

    ``Backtester`` already enforces one entry per calendar day via ``last_buy_date``.
    The live risk layer's daily-loss gate is modeled here on top of ``_open_position``
    so a second same-day attempt (as risk manager would see) is still fail-closed.
    """
    capital = 100_000.0
    cap_pct = 5.0
    fraction = cap_pct / 100.0
    engine = DailyLossAwareBacktester(
        {},
        daily_loss_cap_pct=1.0,
        initial_capital=capital,
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
        max_position_cap_pct=cap_pct,
    )
    day = datetime(2024, 2, 20)
    next_day = datetime(2024, 2, 21)
    signal = {
        "enter": True,
        "exit": False,
        "score": 40.0,
        "stop_loss": 90.0,
        "target_price": 200.0,
        "position_fraction": fraction,
    }

    # First entry of the day is allowed.
    first = engine._open_position(signal, 100.0, 100.0, day, capital)
    assert first is not None
    assert engine.allowed_entry_dates == [day]

    # Simulate a stop that breaches the 1% daily loss budget (₺1_000).
    engine._roll_day(day)
    engine.daily_realized_pnl = -1_500.0
    assert engine._daily_loss_limit_reached() is True

    blocked = engine._open_position(signal, 100.0, 100.0, day, capital)
    assert blocked is None
    assert day in engine.blocked_entry_dates

    # Next calendar day rolls the ledger → entries allowed again.
    allowed = engine._open_position(signal, 100.0, 100.0, next_day, capital)
    assert allowed is not None
    assert next_day in engine.allowed_entry_dates
    assert engine.daily_realized_pnl == 0.0  # rolled on new day before open


def test_sideways_market_produces_fewer_or_zero_trades_vs_trending() -> None:
    """Yatay piyasa: nötr indikatörler → işlem sayısı yükselen trende göre düşük."""
    capital = 10_000.0
    trending = Backtester(
        initial_capital=capital,
        indicators=IdentityIndicators(),
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
    )
    sideways = Backtester(
        initial_capital=capital,
        indicators=IdentityIndicators(),
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
    )
    with _zero_cost_settings():
        up = trending.run("TREND.IS", rising_trend_frame(160), verbose=False)
        flat = sideways.run("FLAT.IS", sideways_frame(160), verbose=False)

    assert up is not None
    assert flat is not None
    assert flat.total_trades <= up.total_trades
    # Pure flat tape with neutral RSI should not invent a bullish binge.
    assert flat.total_trades == 0 or flat.total_trades < max(up.total_trades, 1)


# ---------------------------------------------------------------------------
# Risk limits on every trade
# ---------------------------------------------------------------------------


def test_all_trades_respect_max_position_cap_pct_on_scripted_path() -> None:
    capital = 50_000.0
    cap_pct = 5.0
    fraction = cap_pct / 100.0
    script = {
        55: {
            "enter": True,
            "exit": False,
            "score": 30.0,
            "stop_loss": 50.0,
            "target_price": 10_000.0,
            "position_fraction": fraction,
        },
        90: {
            "enter": False,
            "exit": True,
            "score": -20.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        },
    }
    engine = ScriptedBacktester(
        script,
        initial_capital=capital,
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
        max_position_cap_pct=cap_pct,
    )
    with _zero_cost_settings():
        result = engine.run("CAP.IS", rising_trend_frame(), verbose=False)

    assert result is not None
    assert result.trades
    _assert_trades_respect_position_cap(result, capital=capital, cap_pct=cap_pct)
    # Exact notional should be ~ cap (integer share rounding).
    trade = result.trades[0]
    assert trade.entry_notional_tl <= capital * fraction + trade.entry_price


def test_oversize_fraction_is_still_bounded_by_available_capital() -> None:
    """Even if a signal asks for 100% fraction, notional cannot exceed deployable capital."""
    capital = 20_000.0
    script = {
        55: {
            "enter": True,
            "exit": False,
            "score": 45.0,
            "stop_loss": 10.0,
            "target_price": 10_000.0,
            "position_fraction": 1.0,
        },
        70: {
            "enter": False,
            "exit": True,
            "score": -10.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        },
    }
    engine = ScriptedBacktester(
        script,
        initial_capital=capital,
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
        max_position_cap_pct=100.0,
    )
    with _zero_cost_settings():
        result = engine.run("FULL.IS", rising_trend_frame(), verbose=False)

    assert result is not None
    assert result.trades
    assert result.trades[0].entry_notional_tl <= capital + 1e-6


# ---------------------------------------------------------------------------
# Vectorized vs iterative consistency
# ---------------------------------------------------------------------------


def test_vectorized_and_iterative_paths_agree_on_cyclic_frame() -> None:
    df = cyclic_signal_frame()
    vectorized = Backtester(
        initial_capital=10_000,
        indicators=IdentityIndicators(),
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
    )
    iterative = IterativeBacktester(
        initial_capital=10_000,
        indicators=IdentityIndicators(),
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
    )
    with _zero_cost_settings():
        v = vectorized.run("VEC.IS", df, verbose=False)
        i = iterative.run("ITR.IS", df, verbose=False)

    assert v is not None and i is not None
    assert v.total_trades == i.total_trades
    assert abs(v.final_capital - i.final_capital) <= 1e-6
    assert abs(v.total_return_pct - i.total_return_pct) <= 0.01


def test_insufficient_history_returns_none() -> None:
    engine = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    short = rising_trend_frame(n=20)
    assert engine.run("SHORT.IS", short, verbose=False) is None


def test_backtest_result_schema_is_stable() -> None:
    """Result object exposes the metrics consumers/UI rely on."""
    capital = 10_000.0
    script = {
        55: {
            "enter": True,
            "exit": False,
            "score": 30.0,
            "stop_loss": 50.0,
            "target_price": 10_000.0,
            "position_fraction": 0.05,
        },
        80: {
            "enter": False,
            "exit": True,
            "score": -20.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        },
    }
    engine = ScriptedBacktester(
        script,
        initial_capital=capital,
        commission_buy_pct=0.0,
        commission_sell_pct=0.0,
        slippage_pct=0.0,
        max_position_cap_pct=5.0,
    )
    with _zero_cost_settings():
        result = engine.run("SCHEMA.IS", rising_trend_frame(), verbose=False)

    assert result is not None
    payload = result.to_dict()
    for key in (
        "ticker",
        "initial_capital",
        "final_capital",
        "total_return_pct",
        "total_trades",
        "max_drawdown_pct",
        "sharpe_ratio",
        "trades",
    ):
        assert key in payload
    assert isinstance(result.trades[0], BacktestTrade)
