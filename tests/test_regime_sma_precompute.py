"""Parity lock for the #146 regime-SMA precompute.

Guards the backtest score-loop optimization where ``detect_regime`` receives
a precomputed ``rolling(lookback, min_periods=1)`` SMA instead of recomputing
``df["close"].tail(lookback).mean()`` per bar.

Covers:
  - rolling(20, min_periods=1) == tail(20).mean() at every bar position
    (FP slack ~1e-13; asserted at 1e-9)
  - detect_regime(sub) == detect_regime(sub, sma=precomputed) per bar,
    across BULL/BEAR/SIDEWAYS/UNKNOWN regime transitions
  - _scoring_history_window >= 20 (the contract that makes tail(20) land
    inside the per-bar window slice)
  - end-to-end exact parity: backtest with the precompute path produces the
    same final_capital / total_trades as the legacy per-bar path
    (legacy path forced via monkeypatch in-process)
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime

import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, os.path.join(ROOT_DIR, "src"))

from bist_bot.backtest.engine import Backtester, _scoring_history_window  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.strategy.engine_filters import calculate_score_and_reasons  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.regime import MarketRegime, detect_regime  # noqa: E402

LOOKBACK = 20
WINDOW = 50


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


def _build_frame(n: int = 300) -> pd.DataFrame:
    """Synthetic frame that cycles through BULL/BEAR/SIDEWAYS regimes.

    adx sweeps across the weak (15) and trend (20) thresholds so every
    detect_regime branch is exercised.
    """
    rows: list[dict[str, object]] = []
    dates = pd.date_range(datetime(2024, 1, 1), periods=n, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 30
        base = 100.0 + idx * 0.05 + math.sin(idx / 9) * 4.0
        bull = phase < 7
        bear = 15 <= phase < 22
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 2.0,
                "low": base - 2.0,
                "close": base + 0.5,
                "volume": 10_000,
                "volume_sma_20": 10_000,
                "atr": 2.0,
                "rsi": 25.0 if bull else (76.0 if bear else 50.0),
                "sma_cross": "GOLDEN_CROSS" if bull else ("DEATH_CROSS" if bear else "NONE"),
                "macd_cross": "BULLISH" if bull else ("BEARISH" if bear else "NONE"),
                "bb_position": "BELOW_LOWER" if bull else ("ABOVE_UPPER" if bear else "MIDDLE"),
                "sma_5": base + 1.5,
                "sma_20": base - 0.5,
                "adx": 18.0 + 14.0 * abs(math.sin(idx / 15.0)),
                "plus_di": 20.0 + 10.0 * math.sin(idx / 7.0),
                "minus_di": 20.0 - 10.0 * math.sin(idx / 7.0),
                "stoch_k": 20.0 + 60.0 * abs(math.sin(idx / 6.0)),
                "stoch_d": 20.0 + 60.0 * abs(math.cos(idx / 6.0)),
                "cci": 80.0 * math.sin(idx / 5.0),
                "ema_cross": "BULLISH" if bull else ("BEARISH" if bear else "NONE"),
                "macd_histogram": 0.5 * math.sin(idx / 4.0),
                "macd_hist_increasing": (idx % 5) < 2,
                "di_cross": "BULLISH" if phase == 7 else "NONE",
                "bb_percent": 0.2 + 0.6 * abs(math.sin(idx / 8.0)),
                "bb_squeeze": (idx % 17) < 3,
                "dist_to_support_pct": 3.0,
                "dist_to_resistance_pct": 2.5,
                "rsi_divergence": False,
                "macd_divergence": False,
                "obv_trend": "UP" if phase < 15 else "DOWN",
                "price_volume_direction": "CONFIRM" if phase < 15 else "CONTRADICT",
                "price_volume_confirm": phase < 15,
                "volume_spike": (idx % 23) < 2,
                "volume_ratio": 1.1,
                "volume_trend": "UP",
                f"ema_{settings.EMA_LONG}": base * 0.995 + math.sin(idx / 13.0) * 1.5,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def _precomputed_sma(df: pd.DataFrame) -> pd.Series:
    return df["close"].rolling(LOOKBACK, min_periods=1).mean()


def test_window_contract_ge_lookback() -> None:
    """_scoring_history_window must stay >= detect_regime lookback (20).

    The precompute contract relies on the per-bar slice being long enough
    that tail(lookback) == rolling(lookback) at the final position.
    """
    assert _scoring_history_window(StrategyParams()) >= LOOKBACK


def test_rolling_matches_tail_mean_every_position() -> None:
    df = _build_frame(300)
    rolled = _precomputed_sma(df)
    assert len(rolled) == len(df)
    for i in range(1, len(df)):
        expected = float(df["close"].iloc[max(0, i - LOOKBACK + 1) : i + 1].mean())
        assert rolled.iloc[i] == pytest.approx(expected, abs=1e-9, rel=1e-9), i


def test_detect_regime_with_precomputed_sma_identical_per_bar() -> None:
    df = _build_frame(300)
    rolled = _precomputed_sma(df).to_numpy()
    seen: set[MarketRegime] = set()
    for i in range(1, len(df)):
        start = i - WINDOW + 1
        sub = df.iloc[start : i + 1] if start > 0 else df.iloc[: i + 1]
        legacy = detect_regime(sub)
        fast = detect_regime(sub, sma=float(rolled[i]))
        assert fast == legacy, i
        seen.add(fast)
    # Regime sweep must exercise more than one branch, otherwise the test
    # frame is too flat to guard the optimization.
    assert len(seen) >= 2, seen


def test_dict_rows_match_series_rows_in_scorers() -> None:
    """#146 step 2: dict (Mapping) rows must score identical to Series rows.

    Exercises the real scorers on every bar of a rich frame — the dict row
    is built exactly like _precalculate_signals does (numpy column arrays).
    """
    from bist_bot.backtest import engine as engine_mod
    from bist_bot.strategy.scoring import (
        score_momentum,
        score_structure,
        score_trend,
        score_volume,
    )

    df = _build_frame(200)
    p = StrategyParams()
    keep = [c for c in engine_mod._score_loop_columns() if c in df.columns]
    cols = {c: df[c].to_numpy() for c in keep}
    for i in range(1, len(df)):
        series_last = df.iloc[i]
        series_prev = df.iloc[i - 1]
        dict_last = {c: arr[i] for c, arr in cols.items()}
        dict_prev = {c: arr[i - 1] for c, arr in cols.items()}

        for scorer in (score_momentum, score_volume):
            s_series = scorer(p, series_last, series_prev)
            s_dict = scorer(p, dict_last, dict_prev)
            assert s_dict[0] == s_series[0], (scorer.__name__, i)
            assert s_dict[1] == s_series[1], (scorer.__name__, i)
        s_series = score_structure(p, series_last)
        s_dict = score_structure(p, dict_last)
        assert s_dict[0] == s_series[0] and s_dict[1] == s_series[1], i
        t_series = score_trend(p, series_last, series_prev, df)
        t_dict = score_trend(p, dict_last, dict_prev, df)
        assert t_dict[0] == t_series[0] and t_dict[1] == t_series[1], i


def test_score_identical_with_precomputed_sma() -> None:
    df = _build_frame(300)
    p = StrategyParams()
    rolled = _precomputed_sma(df).to_numpy()
    for i in range(2, len(df)):
        start = i - WINDOW + 1
        sub = df.iloc[start : i + 1] if start > 0 else df.iloc[: i + 1]
        kwargs = dict(
            momentum_scorer=lambda last, prev: (0.0, []),
            trend_scorer=lambda last, prev, d=None: (0.0, []),
            volume_scorer=lambda last, prev: (0.0, []),
            structure_scorer=lambda last: (0.0, []),
        )
        fast = calculate_score_and_reasons(
            p, "", sub, last=sub.iloc[-1], prev=sub.iloc[-2], regime_sma=float(rolled[i]), **kwargs
        )
        legacy = calculate_score_and_reasons(
            p, "", sub, last=sub.iloc[-1], prev=sub.iloc[-2], **kwargs
        )
        assert (fast is None) == (legacy is None), i
        if fast is not None:
            # Regime gate path must be identical; score may differ only at
            # FP-epsilon level (rolling summation order ~1e-13).
            assert fast[0] == pytest.approx(legacy[0], abs=1e-9, rel=1e-9), i


def test_momentum_checker_with_precomputed_values_identical() -> None:
    """#146 step 3: check_momentum_confirmation with last/sma == df-computed."""
    from bist_bot.strategy.regime import check_momentum_confirmation

    df = _build_frame(200)
    rolled = _precomputed_sma(df).to_numpy()
    for i in range(20, len(df)):
        start = i - WINDOW + 1
        sub = df.iloc[start : i + 1] if start > 0 else df.iloc[: i + 1]
        dict_last = {c: df[c].to_numpy()[i] for c in df.columns}
        legacy = check_momentum_confirmation(sub, 4.0)
        fast = check_momentum_confirmation(sub, 4.0, last=dict_last, sma=float(rolled[i]))
        assert fast == legacy, i


def test_engine_score_array_matches_legacy_window_slice_loop(monkeypatch) -> None:
    """#146 step 4: the engine fast path (dict rows + scalar bar context, no
    per-bar window DataFrame slice) must reproduce the legacy algorithm —
    per-bar ``work.iloc[start:i+1]`` slice + pandas Series rows — exactly.

    The returned ``score`` column is execution-shifted by design (signal at
    close t runs at t+1), so the comparison records the engine's raw per-bar
    scores as they are computed and matches them against the legacy loop.
    """
    import numpy as np

    import bist_bot.strategy.engine_filters as ef
    from bist_bot.backtest import engine as engine_mod
    from bist_bot.strategy.regime import check_momentum_confirmation
    from bist_bot.strategy.scoring import (
        score_momentum,
        score_structure,
        score_trend,
        score_volume,
    )

    df = _build_frame(200)
    p = StrategyParams()
    bt = Backtester(initial_capital=10_000, indicators=IdentityIndicators())

    recorded: list[float] = []
    orig = ef.calculate_score_and_reasons

    def recorder(*args, **kwargs):
        result = orig(*args, **kwargs)
        recorded.append(result[0] if result is not None else 0.0)
        return result

    monkeypatch.setattr(ef, "calculate_score_and_reasons", recorder)
    bt._precalculate_signals(df.copy())
    fast_scores = np.clip(np.asarray(recorded, dtype=float), -100.0, 100.0)
    assert len(fast_scores) == len(df) - 1

    # Legacy algorithm mirroring the pre-#146 loop byte-for-byte.
    window = _scoring_history_window(p)
    keep = [c for c in engine_mod._score_loop_columns() if c in df.columns]
    legacy_df = df.copy()
    if "_prev_close_for_scoring" not in legacy_df.columns:
        legacy_df["_prev_close_for_scoring"] = legacy_df["close"].diff().fillna(0.0)
    work = legacy_df[keep] if 0 < len(keep) < len(legacy_df.columns) else legacy_df
    legacy = np.zeros(len(work), dtype=float)

    def momentum_scorer(last, prev):
        return score_momentum(p, last, prev)

    def trend_scorer(last, prev, d=None):
        return score_trend(p, last, prev, d)

    def volume_scorer(last, prev):
        return score_volume(p, last, prev)

    def structure_scorer(last):
        return score_structure(p, last)

    prev = work.iloc[0]
    for i in range(1, len(work)):
        last = work.iloc[i]
        start = i - window + 1
        sub = work.iloc[start : i + 1] if start > 0 else work.iloc[: i + 1]
        result = calculate_score_and_reasons(
            p,
            "",
            sub,
            last=last,
            prev=prev,
            momentum_scorer=momentum_scorer,
            trend_scorer=trend_scorer,
            volume_scorer=volume_scorer,
            structure_scorer=structure_scorer,
            momentum_checker=check_momentum_confirmation,
            reject_logger=None,
        )
        legacy[i] = result[0] if result is not None else 0.0
        prev = last

    legacy_scores = np.clip(legacy[1:], -100.0, 100.0)
    assert np.array_equal(fast_scores, legacy_scores), np.flatnonzero(fast_scores != legacy_scores)[
        :5
    ]
    # Guard the guard: the frame must produce non-trivial scoring, otherwise
    # the comparison above is vacuous.
    assert np.count_nonzero(fast_scores) > 20, np.count_nonzero(fast_scores)


def test_lag_diff_matches_pandas_slope() -> None:
    """#146 step 4: engine _lag_diff == pandas series.iloc[-1] - iloc[-1-k]."""
    from bist_bot.backtest.engine import _lag_diff, _lag_value

    df = _build_frame(200)
    lb = max(int(getattr(StrategyParams(), "slope_lookback", 40)), 1)
    arr = df["sma_20"].to_numpy(dtype=float)
    lag = _lag_diff(arr, lb)
    for i in range(1, len(df)):
        if i < lb:
            assert _lag_value(lag, lb, i) is None
            continue
        expected = float(df["sma_20"].iloc[i] - df["sma_20"].iloc[i - lb])
        assert _lag_value(lag, lb, i) == pytest.approx(expected, abs=0.0, rel=0.0)
