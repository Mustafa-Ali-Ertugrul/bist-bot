"""Tests for day-based walk-forward validation.

WARNING / UYARI
---------------
If you intentionally change default train/test/step day windows, cost bps
defaults, or the overfitting return ratio in
``bist_bot.validation.walk_forward``, update the expected window counts and
flag assertions below consciously.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from bist_bot.backtest.models import BacktestResult, CostModel
from bist_bot.validation.walk_forward import (
    DEFAULT_OVERFITTING_RETURN_RATIO,
    WalkForwardValidator,
)


def build_synthetic_ohlcv(days: int = 500, start: str = "2023-01-01") -> pd.DataFrame:
    """Monotonic rising series with enough history for multi-window WF."""
    dates = pd.date_range(start=start, periods=days, freq="D")
    rows: list[dict[str, float | datetime]] = []
    for idx, date in enumerate(dates):
        base = 100.0 + idx * 0.15
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 1.0,
                "low": base - 1.0,
                "close": base + 0.2,
                "volume": 10_000.0,
                "volume_sma_20": 10_000.0,
                "atr": 1.5,
                "rsi": 35.0 if idx % 20 < 5 else 55.0,
                "sma_cross": "GOLDEN_CROSS" if idx % 40 == 0 else "NONE",
                "macd_cross": "BULLISH" if idx % 20 < 5 else "NONE",
                "bb_position": "BELOW_LOWER" if idx % 20 < 5 else "MIDDLE",
                "sma_5": base + 0.5,
                "sma_20": base - 0.5,
                "ema_200": base - 10.0,
            }
        )
    return pd.DataFrame(rows).set_index("date")


class ScriptedResultBacktester:
    """Deterministic backtester stub keyed by first date of the frame."""

    def __init__(
        self,
        *,
        initial_capital: float,
        cost_model: CostModel | None = None,
        commission_buy_pct: float | None = None,
        commission_sell_pct: float | None = None,
        slippage_pct: float | None = None,
        strategy_params: Any | None = None,
        scenario: str = "balanced",
    ) -> None:
        self.initial_capital = initial_capital
        self.cost_model = cost_model
        self.commission_buy_pct = commission_buy_pct
        self.commission_sell_pct = commission_sell_pct
        self.slippage_pct = slippage_pct
        self.strategy_params = strategy_params
        self.scenario = scenario
        self.calls: list[tuple[str, pd.Timestamp, pd.Timestamp, int]] = []

    def run(self, ticker: str, df: pd.DataFrame, verbose: bool = False) -> BacktestResult:
        _ = verbose
        start = pd.Timestamp(df.index.min())
        end = pd.Timestamp(df.index.max())
        self.calls.append((ticker, start, end, len(df)))

        # Cost awareness: higher bps → lower returns.
        cost_penalty = 0.0
        if self.cost_model is not None:
            cost_penalty = (
                float(self.cost_model.commission_bps) + float(self.cost_model.fixed_slippage_bps)
            ) / 100.0
        elif self.commission_buy_pct is not None or self.slippage_pct is not None:
            cost_penalty = (
                float(self.commission_buy_pct or 0.0) * 10_000
                + float(self.slippage_pct or 0.0) * 10_000
            ) / 100.0

        if self.scenario == "overfit":
            # Train windows (longer) look great; test windows look poor.
            if len(df) >= 100:
                ret = 20.0 - cost_penalty
            else:
                ret = 2.0 - cost_penalty
        elif self.scenario == "cost_sensitive":
            ret = 10.0 - cost_penalty * 2.0
        else:
            ret = 5.0 - cost_penalty

        final = self.initial_capital * (1.0 + ret / 100.0)
        return BacktestResult(
            ticker=ticker,
            period=f"{start.date()}->{end.date()}",
            initial_capital=self.initial_capital,
            final_capital=final,
            total_return_pct=ret,
            total_trades=3 if ret > 0 else 1,
            winning_trades=2 if ret > 0 else 0,
            losing_trades=1,
            win_rate=66.0 if ret > 0 else 0.0,
            avg_profit_pct=2.0,
            avg_loss_pct=-1.0,
            max_drawdown_pct=-3.0 if ret > 0 else -8.0,
            sharpe_ratio=1.1 if ret > 0 else -0.2,
            sortino_ratio=1.2 if ret > 0 else -0.3,
            cagr=ret,
            profit_factor=1.5 if ret > 0 else 0.5,
            avg_trade_pct=ret / 3.0,
            trades=[],
        )


def _factory(scenario: str = "balanced"):
    def factory(
        *,
        initial_capital: float,
        cost_model: CostModel | None,
        commission_buy_pct: float | None,
        commission_sell_pct: float | None,
        slippage_pct: float | None,
        strategy_params: Any | None = None,
    ) -> ScriptedResultBacktester:
        return ScriptedResultBacktester(
            initial_capital=initial_capital,
            cost_model=cost_model,
            commission_buy_pct=commission_buy_pct,
            commission_sell_pct=commission_sell_pct,
            slippage_pct=slippage_pct,
            strategy_params=strategy_params,
            scenario=scenario,
        )

    return factory


def test_build_windows_count_and_sizes() -> None:
    df = build_synthetic_ohlcv(500)
    validator = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=50,
        backtester_factory=_factory(),
    )
    windows = validator.build_windows(df)
    # 500 rows, train=100, test=50, step=50 → starts 0..350 inclusive → 8 windows
    assert len(windows) == 8
    for train_df, test_df in windows:
        assert len(train_df) == 100
        assert len(test_df) == 50


def test_no_lookahead_bias_between_train_and_test() -> None:
    df = build_synthetic_ohlcv(400)
    validator = WalkForwardValidator(
        train_window=120,
        test_window=40,
        step_size=40,
        backtester_factory=_factory(),
    )
    for train_df, test_df in validator.build_windows(df):
        assert pd.Timestamp(test_df.index.min()) > pd.Timestamp(train_df.index.max())
        # Contiguous split: first test row is immediately after last train row in the series.
        train_pos = df.index.get_loc(train_df.index[-1])
        test_pos = df.index.get_loc(test_df.index[0])
        assert test_pos == train_pos + 1


def test_run_aggregates_oos_metrics() -> None:
    df = build_synthetic_ohlcv(400)
    validator = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=50,
        commission_bps=2.0,
        slippage_bps=5.0,
        initial_capital=50_000.0,
        backtester_factory=_factory("balanced"),
    )
    result = validator.run("TEST.IS", df)
    assert result is not None
    assert result.ticker == "TEST.IS"
    assert len(result.windows) >= 3
    assert result.oos_aggregate["count"] == float(len(result.windows))
    assert "mean_total_return_pct" in result.oos_aggregate
    assert "median_sharpe_ratio" in result.oos_aggregate
    assert "std_win_rate" in result.oos_aggregate
    assert result.is_aggregate["count"] == float(len(result.windows))
    # Each window records both IS and OOS returns.
    for window in result.windows:
        assert isinstance(window.train_return_pct, float)
        assert isinstance(window.test_return_pct, float)
        assert window.train_rows == 100
        assert window.test_rows == 50


def test_overfitting_warning_when_oos_much_worse_than_is() -> None:
    df = build_synthetic_ohlcv(400)
    validator = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=50,
        commission_bps=0.0,
        slippage_bps=0.0,
        overfitting_return_ratio=DEFAULT_OVERFITTING_RETURN_RATIO,
        backtester_factory=_factory("overfit"),
        use_cost_model=True,
    )
    result = validator.run("OVERFIT.IS", df)
    assert result is not None
    assert result.has_overfitting_warning
    assert "OVERFITTING_WARNING" in result.flags
    assert (
        result.is_aggregate["mean_total_return_pct"] > result.oos_aggregate["mean_total_return_pct"]
    )


def test_transaction_costs_reduce_returns() -> None:
    df = build_synthetic_ohlcv(350)

    cheap = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=50,
        commission_bps=1.0,
        slippage_bps=1.0,
        backtester_factory=_factory("cost_sensitive"),
    )
    expensive = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=50,
        commission_bps=20.0,
        slippage_bps=30.0,
        backtester_factory=_factory("cost_sensitive"),
    )
    cheap_result = cheap.run("COST.IS", df)
    expensive_result = expensive.run("COST.IS", df)
    assert cheap_result is not None and expensive_result is not None
    assert (
        expensive_result.oos_aggregate["mean_total_return_pct"]
        < cheap_result.oos_aggregate["mean_total_return_pct"]
    )


def test_insufficient_history_returns_none() -> None:
    df = build_synthetic_ohlcv(80)
    validator = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=50,
        backtester_factory=_factory(),
    )
    assert validator.run("SHORT.IS", df) is None


def test_invalid_constructor_args_raise() -> None:
    with pytest.raises(ValueError):
        WalkForwardValidator(train_window=0)
    with pytest.raises(ValueError):
        WalkForwardValidator(test_window=0)
    with pytest.raises(ValueError):
        WalkForwardValidator(step_size=0)
    with pytest.raises(ValueError):
        WalkForwardValidator(commission_bps=-1)
    with pytest.raises(ValueError):
        WalkForwardValidator(initial_capital=0)
    with pytest.raises(ValueError):
        WalkForwardValidator(overfitting_return_ratio=1.5)


def test_backtester_factory_receives_cost_parameters() -> None:
    captured: dict[str, Any] = {}

    def factory(
        *,
        initial_capital: float,
        cost_model: CostModel | None,
        commission_buy_pct: float | None,
        commission_sell_pct: float | None,
        slippage_pct: float | None,
        strategy_params: Any | None = None,
    ) -> ScriptedResultBacktester:
        captured["initial_capital"] = initial_capital
        captured["cost_model"] = cost_model
        captured["commission_buy_pct"] = commission_buy_pct
        captured["commission_sell_pct"] = commission_sell_pct
        captured["slippage_pct"] = slippage_pct
        captured["strategy_params"] = strategy_params
        return ScriptedResultBacktester(
            initial_capital=initial_capital,
            cost_model=cost_model,
            commission_buy_pct=commission_buy_pct,
            commission_sell_pct=commission_sell_pct,
            slippage_pct=slippage_pct,
            strategy_params=strategy_params,
        )

    df = build_synthetic_ohlcv(300)
    validator = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=100,
        commission_bps=3.0,
        slippage_bps=7.0,
        initial_capital=12_345.0,
        backtester_factory=factory,
        use_cost_model=True,
    )
    result = validator.run("CAP.IS", df)
    assert result is not None
    assert captured["initial_capital"] == 12_345.0
    assert captured["cost_model"] is not None
    assert captured["cost_model"].commission_bps == 3.0
    assert captured["cost_model"].fixed_slippage_bps == 7.0
    assert captured["commission_buy_pct"] is None
    assert captured["slippage_pct"] is None


def test_result_to_dict_is_json_friendly() -> None:
    df = build_synthetic_ohlcv(300)
    validator = WalkForwardValidator(
        train_window=100,
        test_window=50,
        step_size=100,
        backtester_factory=_factory(),
    )
    result = validator.run("JSON.IS", df)
    assert result is not None
    payload = result.to_dict()
    assert payload["ticker"] == "JSON.IS"
    assert isinstance(payload["windows"], list)
    assert isinstance(payload["flags"], list)
    assert "oos_aggregate" in payload
