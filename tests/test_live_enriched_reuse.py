"""Parity lock for the live-engine enriched-reuse optimization (#146 live path).

`StrategyBacktester` caches one enriched frame and used to re-run
`indicators.add_all` per bar inside `StrategyEngine.analyze` (O(n^2)).
`analyze(..., pre_enriched=True)` reuses the cache instead.

The only frame-length-dependent part of `add_all` is the divergence
suppression rule in `_add_min_divergence` (the frame's LAST row is always
"NONE"); every other column's last-row value equals the cached full-frame
value. These tests pin that contract and the end-to-end parity.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "src"))

from bist_bot.indicators import TechnicalIndicators  # noqa: E402
from bist_bot.strategy.engine_core import DIVERGENCE_COLUMNS  # noqa: E402


def _frame(n: int) -> pd.DataFrame:
    idx = pd.date_range(datetime(2020, 1, 1), periods=n, freq="D")
    close = 60.0 + 12.0 * np.sin(np.arange(n) / 13.0) + np.arange(n) * 0.02
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "open": np.concatenate([[close[0]], close[:-1]]) * 1.002,
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def test_last_row_divergence_always_none_prefix_independent() -> None:
    """The only frame-length dependence: divergence NONE on the last row."""
    raw = _frame(160)
    for k in range(30, 161, 7):
        pref = TechnicalIndicators().add_all(raw.iloc[:k].copy())
        for col in DIVERGENCE_COLUMNS:
            assert str(pref[col].iloc[k - 1]) == "NONE", (k, col)


def test_other_columns_last_row_match_full_frame_cache() -> None:
    """Every non-divergence column's last-row value == full-frame cache value.

    This is what makes the cache usable: only the divergence columns need the
    pre_enriched last-row correction.
    """
    raw = _frame(160)
    cache = TechnicalIndicators().add_all(raw.copy())
    for k in range(30, 161, 7):
        pref = TechnicalIndicators().add_all(raw.iloc[:k].copy())
        for col in cache.columns:
            if col in DIVERGENCE_COLUMNS:
                continue
            a = pref[col].to_numpy()[-1]
            b = cache[col].to_numpy()[k - 1]
            if cache[col].dtype.kind in "fc":
                assert abs(float(a) - float(b)) < 1e-12, (k, col)
            else:
                assert str(a) == str(b), (k, col)


def test_full_frame_divergence_equals_live_knowledge_one_bar_later() -> None:
    """Backtest consistency: full-frame row t == prefix knowledge at t+1.

    The engine executes signals with shift(1), so the full-frame value at t
    is consumed at t+1 — exactly when the live path can know it. Verifies the
    existing backtest path is not look-ahead contaminated.
    """
    raw = _frame(160)
    full = TechnicalIndicators().add_all(raw.copy())
    for t in range(30, 159, 11):
        later = TechnicalIndicators().add_all(raw.iloc[: t + 2].copy())
        assert str(full["macd_divergence"].iloc[t]) == str(
            later["macd_divergence"].iloc[t]
        ), t


def test_strategy_backtester_enriched_reuse_matches_legacy() -> None:
    """End-to-end: pre_enriched path == legacy per-bar add_all path."""
    from bist_bot.backtest.strategy import StrategyBacktester
    from bist_bot.strategy.engine import StrategyEngine
    from bist_bot.strategy.params import StrategyParams

    params = replace(
        StrategyParams(),
        buy_threshold=10.0,
        sell_threshold=-10.0,
        sideways_extra_threshold=0.0,
    )

    def run(force_legacy: bool):
        sb = StrategyBacktester(
            initial_capital=10_000, engine=StrategyEngine(params=params)
        )
        if force_legacy:
            orig = sb.engine.analyze

            def legacy(ticker, d, enforce_sector_limit=False, **kw):
                kw.pop("pre_enriched", None)
                return orig(ticker, d, enforce_sector_limit=enforce_sector_limit, **kw)

            sb.engine.analyze = legacy  # type: ignore[method-assign]
        return sb.run("T.IS", _frame(200), verbose=False)

    legacy = run(force_legacy=True)
    fast = run(force_legacy=False)
    assert legacy is not None and fast is not None
    assert legacy.final_capital == fast.final_capital
    assert legacy.total_trades == fast.total_trades
    assert len(legacy.trades) == len(fast.trades)
    for a, b in zip(legacy.trades, fast.trades, strict=True):
        assert a.entry_date == b.entry_date
        assert a.exit_date == b.exit_date
        assert a.entry_price == b.entry_price
        assert a.exit_price == b.exit_price
        assert a.profit_pct == b.profit_pct
    # Guard the guard: the frame must actually trade.
    assert legacy.total_trades > 0, legacy.total_trades


def test_prepare_analysis_frame_pre_enriched_blanks_last_divergence() -> None:
    from bist_bot.strategy.engine_core import prepare_analysis_frame

    raw = _frame(80)
    enriched = TechnicalIndicators().add_all(raw.copy())
    enriched.loc[enriched.index[-1], "macd_divergence"] = "BULLISH"
    enriched.loc[enriched.index[-1], "rsi_divergence"] = "BEARISH"
    out, _bias, last, _prev = prepare_analysis_frame(
        TechnicalIndicators(),
        enriched,
        trend_df=enriched,
        multi_timeframe=False,
        pre_enriched=True,
    )
    for col in DIVERGENCE_COLUMNS:
        assert str(out[col].iloc[-1]) == "NONE"
        assert str(last[col]) == "NONE"


def test_prepare_analysis_frame_pre_enriched_does_not_recompute() -> None:
    """pre_enriched must not call add_all (the whole point of the change)."""

    class ExplodingIndicators:
        def add_all(self, df):  # pragma: no cover - must never run
            raise AssertionError("add_all must not be called when pre_enriched")

    from bist_bot.strategy.engine_core import prepare_analysis_frame

    raw = _frame(60)
    enriched = TechnicalIndicators().add_all(raw.copy())
    prepare_analysis_frame(
        ExplodingIndicators(),
        enriched,
        trend_df=enriched,
        multi_timeframe=False,
        pre_enriched=True,
    )


def test_prepare_analysis_frame_default_still_enriches() -> None:
    from bist_bot.strategy.engine_core import prepare_analysis_frame

    raw = _frame(60)
    out, _bias, _last, _prev = prepare_analysis_frame(
        TechnicalIndicators(),
        raw,
        trend_df=raw,
        multi_timeframe=False,
    )
    assert "macd_divergence" in out.columns
    assert "rsi" in out.columns


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
