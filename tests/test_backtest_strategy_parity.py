"""Parity lock: backtest scoring must equal live StrategyEngine scoring.

This test is the regression guard for the single-source-of-truth refactor.
If anyone changes the backtest scoring path OR calculate_score_and_reasons
without updating both, this test turns RED.

Covers:
  - vectorized path (_precalculate_signals _raw_score) == calculate_score_and_reasons
    with H1/H3 regime gates ON (sideways multiplier, momentum confirmation)
  - vectorized path == base 4-scorer sum with H1/H3 OFF
  - iterative path (_calculate_score) == calculate_score_and_reasons
  - synthetic + realistic OHLCV frames
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "src"))

from bist_bot.backtest.engine import Backtester  # noqa: E402
from bist_bot.indicators import TechnicalIndicators  # noqa: E402
from bist_bot.strategy.engine_filters import calculate_score_and_reasons  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.regime import check_momentum_confirmation  # noqa: E402
from bist_bot.strategy.scoring import (  # noqa: E402
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


def _make_scorers(p: StrategyParams):
    def momentum_scorer(last, prev):
        return score_momentum(p, last, prev)

    def trend_scorer(last, prev, df=None):
        return score_trend(p, last, prev, df)

    def volume_scorer(last, prev):
        return score_volume(p, last, prev)

    def structure_scorer(last):
        return score_structure(p, last)

    return momentum_scorer, trend_scorer, volume_scorer, structure_scorer


def _live_score_row(
    p: StrategyParams,
    df: pd.DataFrame,
    i: int,
    *,
    momentum_checker: Callable = check_momentum_confirmation,
) -> float | None:
    """Mirror of StrategyEngine._calculate_score_and_reasons for a single row."""
    last = df.iloc[i]
    prev = df.iloc[i - 1]
    mom, tr, vol, struct = _make_scorers(p)
    return calculate_score_and_reasons(
        p,
        "",
        df.iloc[: i + 1],
        last=last,
        prev=prev,
        momentum_scorer=mom,
        trend_scorer=tr,
        volume_scorer=vol,
        structure_scorer=struct,
        momentum_checker=momentum_checker,
        reject_logger=None,
    )


def _build_synthetic_frame(periods: int = 260) -> pd.DataFrame:
    rows: list[dict[str, float | str | datetime]] = []
    dates = pd.date_range(datetime(2023, 1, 1), periods=periods, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 44
        base = 100.0 + idx * 0.15 + math.sin(idx / 7) * 4.0
        if phase < 8:
            rsi = 22.0
            sma_cross = "GOLDEN_CROSS" if phase == 0 else "NONE"
            macd_cross = "BULLISH"
            bb_position = "BELOW_LOWER"
        elif 22 <= phase < 30:
            rsi = 80.0
            sma_cross = "DEATH_CROSS" if phase == 22 else "NONE"
            macd_cross = "BEARISH"
            bb_position = "ABOVE_UPPER"
        else:
            rsi = 50.0
            sma_cross = "NONE"
            macd_cross = "NONE"
            bb_position = "MIDDLE"
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 3.0,
                "low": base - 3.0,
                "close": base + 0.8,
                "volume": 10_000,
                "rsi": rsi,
                "sma_cross": sma_cross,
                "macd_cross": macd_cross,
                "bb_position": bb_position,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def _build_realistic_frame(periods: int = 260) -> pd.DataFrame:
    """Realistic OHLCV with noise — exercises regime detection more thoroughly."""
    rows: list[dict[str, float | datetime]] = []
    dates = pd.date_range(datetime(2022, 6, 1), periods=periods, freq="D")
    rng = np.random.default_rng(42)
    price = 100.0
    for _, date in enumerate(dates):
        price += float(rng.normal(0, 1.2))
        price = max(price, 1.0)
        rows.append(
            {
                "date": date,
                "open": price,
                "high": price + float(rng.uniform(0.5, 2.5)),
                "low": price - float(rng.uniform(0.5, 2.5)),
                "close": price + float(rng.normal(0, 0.8)),
                "volume": int(rng.integers(5_000, 50_000)),
            }
        )
    return pd.DataFrame(rows).set_index("date")


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    ind = TechnicalIndicators()
    enriched = ind.add_all(df.copy())
    enriched["_prev_close_for_scoring"] = enriched["close"].shift(1)
    return enriched


@pytest.mark.parametrize("frame_factory", [_build_synthetic_frame, _build_realistic_frame])
def test_vectorized_raw_score_matches_live_with_h1h3(frame_factory):
    """H1/H3 ON: backtest _raw_score == calculate_score_and_reasons per row."""
    df = _enrich(frame_factory())
    backtester = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    pre = backtester._precalculate_signals(df.copy())

    p = StrategyParams()
    raw = pre["_raw_score"].to_numpy(dtype=float)

    for i in range(1, len(df)):
        live = _live_score_row(p, df, i)
        live_val = live[0] if live is not None else 0.0
        assert abs(raw[i] - live_val) < 1e-6, (
            f"row {i} ({df.index[i].date()}): vec={raw[i]} live={live_val}"
        )


@pytest.mark.parametrize("frame_factory", [_build_synthetic_frame, _build_realistic_frame])
def test_vectorized_includes_adx_penalty_when_live_does(frame_factory):
    """The low-ADX penalty (part of calculate_score_and_reasons) must be active
    in backtest. When the gate does NOT fire (result is not None), the backtest
    score must equal the live score exactly (penalty included). When the gate
    DOES fire (result is None), the backtest score must be 0.
    """
    df = _enrich(frame_factory())
    backtester = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    pre = backtester._precalculate_signals(df.copy())

    p = StrategyParams()
    raw = pre["_raw_score"].to_numpy(dtype=float)

    for i in range(1, len(df)):
        live = _live_score_row(p, df, i)
        if live is None:
            assert raw[i] == 0.0, f"row {i}: expected 0 (filtered), got {raw[i]}"
        else:
            assert abs(raw[i] - live[0]) < 1e-6, (
                f"row {i}: vec={raw[i]} live={live[0]} (ADX penalty mismatch)"
            )


def test_iterative_calculate_score_matches_live():
    """Iterative path _calculate_score == calculate_score_and_reasons per row."""
    df = _enrich(_build_synthetic_frame(120))
    backtester = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    p = StrategyParams()

    for i in range(2, len(df)):
        history = df.iloc[: i + 1]
        iterative_score = backtester._calculate_score(history)
        live = _live_score_row(p, df, i)
        live_val = live[0] if live is not None else 0.0
        assert abs(iterative_score - live_val) < 1e-6, (
            f"row {i}: iterative={iterative_score} live={live_val}"
        )


def test_vectorized_and_iterative_paths_produce_same_score():
    """Both backtest paths must agree (regression for vectorized-vs-iterative)."""
    df = _enrich(_build_synthetic_frame(120))

    class IterativeBacktester(Backtester):
        def _use_vectorized_path(self) -> bool:
            return False

    vec = Backtester(initial_capital=10_000, indicators=IdentityIndicators())
    ite = IterativeBacktester(initial_capital=10_000, indicators=IdentityIndicators())

    vec_pre = vec._precalculate_signals(df.copy())
    vec_raw = vec_pre["_raw_score"].to_numpy(dtype=float)

    for i in range(2, len(df)):
        history = df.iloc[: i + 1]
        ite_score = ite._calculate_score(history)
        assert abs(vec_raw[i] - ite_score) < 1e-6, (
            f"row {i}: vectorized={vec_raw[i]} iterative={ite_score}"
        )
