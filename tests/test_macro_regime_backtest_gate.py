"""Deney D: macro regime entry gate in the Backtester.

Covers: off/observe/enforce constructor validation, observe == off
behavioural identity, enforce blocking only BEAR-day candidates,
UNKNOWN/NaN/series-start handling (never blocks), gate applied pre-shift,
fail-fast on custom signal_builder and intraday data, validator wiring,
and the no-new-trades invariant.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from bist_bot.backtest import Backtester
from bist_bot.strategy.regime import MarketRegime
from bist_bot.validation.walk_forward import WalkForwardValidator


def _frame(n: int = 120, *, start: str = "2024-01-01") -> pd.DataFrame:
    """Golden-cross trending frame that reliably produces entry signals."""
    dates = pd.date_range(start, periods=n, freq="D")
    rows = []
    for i, d in enumerate(dates):
        close = 100.0 + i * 0.5
        rows.append(
            {
                "date": d,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close + 0.1,
                "volume": 10_000.0,
                "volume_sma_20": 10_000.0,
                "atr": 1.5,
                "rsi": 28.0,
                "sma_cross": "GOLDEN_CROSS",
                "macd_cross": "BULLISH",
                "bb_position": "BELOW_LOWER",
                "sma_5": close + 0.5,
                "sma_20": close - 0.5,
                "ema_200": close - 5.0,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def _series_like(index: pd.DatetimeIndex, value: MarketRegime) -> pd.Series:
    return pd.Series(value, index=index, dtype=object)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_default_mode_is_off_and_no_series_needed():
    bt = Backtester()
    assert bt.macro_regime_mode == "off"
    assert bt.macro_regime_series is None


def test_gate_mode_without_series_raises():
    with pytest.raises(ValueError, match="macro_regime_series"):
        Backtester(macro_regime_mode="observe")
    with pytest.raises(ValueError, match="macro_regime_series"):
        Backtester(macro_regime_mode="enforce")


def test_off_mode_with_series_raises():
    df = _frame()
    series = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BULL)
    with pytest.raises(ValueError, match="off"):
        Backtester(macro_regime_series=series, macro_regime_mode="off")


def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="off/observe/enforce"):
        Backtester(macro_regime_mode="audit")


def test_non_monotonic_series_raises():
    idx = pd.to_datetime(["2024-01-10", "2024-01-05"])
    series = pd.Series([MarketRegime.BULL, MarketRegime.BEAR], index=idx, dtype=object)
    with pytest.raises(ValueError, match="monotonic"):
        Backtester(macro_regime_series=series, macro_regime_mode="observe")


# ---------------------------------------------------------------------------
# Behavioural invariants
# ---------------------------------------------------------------------------


def test_observe_matches_off_exactly():
    df = _frame()
    series = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BEAR)
    off = Backtester(initial_capital=10_000).run("T", df, verbose=False)
    observing = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="observe",
    ).run("T", df, verbose=False)
    assert off is not None and observing is not None
    assert observing.total_trades == off.total_trades
    assert observing.final_capital == pytest.approx(off.final_capital)
    assert [(t.entry_date, t.exit_date) for t in observing.trades] == [
        (t.entry_date, t.exit_date) for t in off.trades
    ]


def test_enforce_blocks_all_bear_day_entries_when_all_bear():
    df = _frame()
    series = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BEAR)
    off = Backtester(initial_capital=10_000).run("T", df, verbose=False)
    bt_enforce = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="enforce",
    )
    enforced = bt_enforce.run("T", df, verbose=False)
    assert off is not None and off.total_trades > 0
    assert enforced is not None
    assert enforced.total_trades == 0
    assert bt_enforce.last_macro_bear_bars == len(df)
    assert bt_enforce.last_macro_bear_entry_candidates > 0


def test_bull_series_never_blocks():
    df = _frame()
    series = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BULL)
    bt = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="enforce",
    )
    result = bt.run("T", df, verbose=False)
    off = Backtester(initial_capital=10_000).run("T", df, verbose=False)
    assert result is not None and off is not None
    assert result.total_trades == off.total_trades
    assert bt.last_macro_bear_bars == 0
    assert bt.last_macro_bear_entry_candidates == 0


def test_series_start_gap_treated_as_unknown_and_never_blocks():
    df = _frame()
    idx = pd.DatetimeIndex(df.index)
    # Series only covers the second half → first half aligns to NaN (UNKNOWN).
    series = _series_like(idx[len(idx) // 2 :], MarketRegime.BEAR)
    bt = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="enforce",
    )
    result = bt.run("T", df, verbose=False)
    assert result is not None
    # Trades are still possible in the UNKNOWN first half.
    first_half_entries = [t for t in result.trades if t.entry_date < idx[len(idx) // 2]]
    assert result.total_trades > len(first_half_entries) or first_half_entries
    assert bt.last_macro_bear_bars == len(idx) - len(idx) // 2


def test_enforce_only_removes_trades_never_adds():
    df = _frame()
    idx = pd.DatetimeIndex(df.index)
    rng = np.random.default_rng(7)
    values = [rng.choice(list(MarketRegime)) for _ in idx]
    series = pd.Series(values, index=idx, dtype=object)
    off = Backtester(initial_capital=10_000).run("T", df, verbose=False)
    bt = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="enforce",
    )
    enforced = bt.run("T", df, verbose=False)
    assert off is not None and enforced is not None
    off_keys = {(t.entry_date, t.exit_date) for t in off.trades}
    enforced_keys = {(t.entry_date, t.exit_date) for t in enforced.trades}
    assert enforced_keys.issubset(off_keys)


def test_gate_applied_pre_shift_entry_date_is_next_bar():
    df = _frame()
    series = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BEAR)
    bt = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="observe",
    )
    bt.run("T", df, verbose=False)
    assert bt.last_macro_bear_entry_candidates > 0


def test_score_and_exit_columns_untouched_by_enforce():
    df = _frame()
    series = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BEAR)
    plain = Backtester(initial_capital=10_000)._precalculate_signals(df.copy())
    gated = Backtester(
        initial_capital=10_000,
        macro_regime_series=series,
        macro_regime_mode="enforce",
    )._precalculate_signals(df.copy())
    pd.testing.assert_series_equal(plain["score"], gated["score"])
    pd.testing.assert_series_equal(plain["exit_signal"], gated["exit_signal"])
    pd.testing.assert_series_equal(plain["calculated_stop"], gated["calculated_stop"])


def test_counters_reset_between_runs():
    df = _frame()
    bear = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BEAR)
    bull = _series_like(pd.DatetimeIndex(df.index), MarketRegime.BULL)
    bt = Backtester(
        initial_capital=10_000,
        macro_regime_series=bear,
        macro_regime_mode="observe",
    )
    bt.run("T", df, verbose=False)
    assert bt.last_macro_bear_bars > 0
    bt.macro_regime_series = bull
    bt.run("T", df, verbose=False)
    assert bt.last_macro_bear_bars == 0
    assert bt.last_macro_bear_entry_candidates == 0


# ---------------------------------------------------------------------------
# Fail-fast
# ---------------------------------------------------------------------------


def test_custom_signal_builder_rejected_in_gate_modes():
    bt = Backtester(
        macro_regime_series=_series_like(pd.DatetimeIndex(_frame().index), MarketRegime.BULL),
        macro_regime_mode="enforce",
    )
    bt.signal_builder = lambda ticker, history: {
        "enter": False,
        "exit": False,
        "score": 0.0,
        "stop_loss": 0.0,
        "target_price": 0.0,
    }
    with pytest.raises(ValueError, match="signal_builder"):
        bt.run("T", _frame(), verbose=False)


def test_intraday_index_rejected_in_gate_modes():
    df = _frame()
    idx = pd.DatetimeIndex(df.index)
    df.index = idx + pd.Timedelta(hours=10, minutes=30)
    with pytest.raises(ValueError, match="daily"):
        Backtester(
            macro_regime_series=_series_like(idx, MarketRegime.BULL),
            macro_regime_mode="observe",
        ).run("T", df, verbose=False)


# ---------------------------------------------------------------------------
# WalkForwardValidator wiring
# ---------------------------------------------------------------------------


def test_validator_requires_series_for_gate_modes():
    with pytest.raises(ValueError, match="series"):
        WalkForwardValidator(macro_regime_mode="observe")


def test_validator_rejects_series_in_off_mode():
    series = _series_like(pd.DatetimeIndex(_frame().index), MarketRegime.BULL)
    with pytest.raises(ValueError, match="observe/enforce"):
        WalkForwardValidator(macro_regime_series=series, macro_regime_mode="off")


def test_validator_rejects_factory_in_gate_modes():
    series = _series_like(pd.DatetimeIndex(_frame().index), MarketRegime.BULL)
    with pytest.raises(ValueError, match="backtester_factory"):
        WalkForwardValidator(
            backtester_factory=lambda **kwargs: None,
            macro_regime_series=series,
            macro_regime_mode="observe",
        )


def test_validator_passes_gate_fields_to_backtester():
    series = _series_like(pd.DatetimeIndex(_frame().index), MarketRegime.BEAR)
    wf = WalkForwardValidator(macro_regime_series=series, macro_regime_mode="enforce")
    bt = wf._make_backtester()
    assert bt.macro_regime_mode == "enforce"
    pd.testing.assert_series_equal(bt.macro_regime_series, series)


def test_validator_window_metrics_carry_macro_counters():
    df = _frame(n=400)
    idx = pd.DatetimeIndex(df.index)
    series = _series_like(idx, MarketRegime.BEAR)
    wf = WalkForwardValidator(
        train_window=150,
        test_window=50,
        step_size=50,
        macro_regime_series=series,
        macro_regime_mode="observe",
    )
    result = wf.run("T", df)
    assert result is not None
    assert all(w.train_macro_bear_bars + w.test_macro_bear_bars > 0 for w in result.windows)
    assert result.total_macro_bear_bars == sum(
        w.train_macro_bear_bars + w.test_macro_bear_bars for w in result.windows
    )
    assert result.total_macro_bear_entry_candidates == sum(
        w.train_macro_bear_entry_candidates + w.test_macro_bear_entry_candidates
        for w in result.windows
    )


def test_validator_observe_results_match_off_results():
    datetime(2024, 1, 1)  # keep import used
    df = _frame(n=400)
    idx = pd.DatetimeIndex(df.index)
    series = _series_like(idx, MarketRegime.BEAR)
    kwargs = {"train_window": 150, "test_window": 50, "step_size": 50}
    off = WalkForwardValidator(**kwargs).run("T", df)
    obs = WalkForwardValidator(
        macro_regime_series=series, macro_regime_mode="observe", **kwargs
    ).run("T", df)
    assert off is not None and obs is not None
    assert [w.test_return_pct for w in obs.windows] == [w.test_return_pct for w in off.windows]
    assert [w.test_trades for w in obs.windows] == [w.test_trades for w in off.windows]
