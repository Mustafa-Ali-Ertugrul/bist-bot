"""Focused verification of EMA initial cross scoring (Asama 2).

Constructs deterministic OHLCV data with a guaranteed EMA long cross point
(bullish and bearish) and asserts that ``score_trend`` emits the expected
score delta and reason text.

Because the project has no real-BIST OHLCV fixture and live network calls
are out of scope, this test uses synthetic data shaped so that the
EMA(200) cross point is unambiguous. If the logic is correct here, it will
trigger on any real-world BIST data exhibiting the same pattern.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.scoring import score_trend

EMA_LONG = settings.EMA_LONG  # 200 in default config


def _build_frame(prices: list[float], volume: float = 1_000_000.0) -> pd.DataFrame:
    n = len(prices)
    close = np.array(prices, dtype=float)
    high = close * 1.001
    low = close * 0.999
    open_ = np.concatenate([[close[0]], close[:-1]])
    vol = np.full(n, volume, dtype=float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol})


def _make_enriched(prices: list[float]) -> pd.DataFrame:
    df = _build_frame(prices)
    ti = TechnicalIndicators()
    return ti.add_all(df)


def test_ema_initial_cross_bullish_scores_positive_and_logs_cross():
    """prev close < EMA long, last close > EMA long: +score_ema_initial_cross."""
    # 230 bars of downtrend (so EMA(200) tracks the high range), then a sharp
    # recovery in the last 2 bars to push price above EMA(200).
    n_pre = 230
    downtrend = [100.0 - 0.05 * i for i in range(n_pre)]
    # Last 2 bars: prev just below EMA(200), last well above.
    recovery = [downtrend[-1], downtrend[-1] + 30.0]
    prices = downtrend + recovery

    enriched = _make_enriched(prices)
    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    ema_col = f"ema_{EMA_LONG}"
    assert ema_col in enriched.columns, f"column {ema_col} missing in {list(enriched.columns)}"
    assert pd.notna(last[ema_col]) and pd.notna(prev[ema_col]), (
        "EMA long should be defined on last 2 bars; lengthen the frame"
    )
    assert prev["close"] < prev[ema_col], "test invariant: prev should be below EMA"
    assert last["close"] > last[ema_col], "test invariant: last should be above EMA"

    params = StrategyParams()
    score, reasons = score_trend(params, last, prev)

    assert score >= params.score_ema_initial_cross, (
        f"expected score >= {params.score_ema_initial_cross} (EMA bullish cross), got {score}"
    )
    assert any("kesti" in r and "yukar" in r for r in reasons), (
        f"expected a 'yukari kesis' reason, got: {reasons}"
    )


def test_ema_initial_cross_bearish_scores_negative_and_logs_cross():
    """prev close > EMA long, last close < EMA long: -score_ema_initial_cross."""
    n_pre = 230
    uptrend = [100.0 + 0.05 * i for i in range(n_pre)]
    # Last 2 bars: prev above EMA(200), last well below.
    decline = [uptrend[-1], uptrend[-1] - 30.0]
    prices = uptrend + decline

    enriched = _make_enriched(prices)
    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    ema_col = f"ema_{EMA_LONG}"
    assert ema_col in enriched.columns
    assert pd.notna(last[ema_col]) and pd.notna(prev[ema_col])
    assert prev["close"] > prev[ema_col]
    assert last["close"] < last[ema_col]

    params = StrategyParams()
    score, reasons = score_trend(params, last, prev)

    assert score <= -params.score_ema_initial_cross, (
        f"expected score <= -{params.score_ema_initial_cross}, got {score}"
    )
    assert any("kesti" in r and ("aşağı" in r or "asagi" in r) for r in reasons), (
        f"expected an 'asagi kesis' reason, got: {reasons}"
    )


def test_ema_initial_cross_disabled_when_already_above_ema():
    """Already-above-EMA continuation should NOT add initial-cross score."""
    # 230 bars of smooth uptrend so EMA(200) is well below the last bars.
    n_pre = 230
    uptrend = [100.0 + 0.05 * i for i in range(n_pre)]
    prices = [*uptrend, uptrend[-1] + 0.1, uptrend[-1] + 0.2]  # last 2 bars stay above

    enriched = _make_enriched(prices)
    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    ema_col = f"ema_{EMA_LONG}"
    assert ema_col in enriched.columns
    assert prev["close"] > prev[ema_col] and last["close"] > last[ema_col]

    params = StrategyParams()
    score, reasons = score_trend(params, last, prev)

    cross_reasons = [r for r in reasons if "kesti" in r]
    assert not cross_reasons, (
        f"expected no 'kesti' reasons in continuation uptrend, got: {cross_reasons}"
    )
    # The base 'already-above-EMA' branch may still let other components
    # (ema_cross, sma_trend, macd, adx) contribute; this test only asserts
    # that the *initial-cross* branch did NOT add a cross-reason.


def test_ema_initial_cross_trips_on_first_recovery_bar():
    """Tightest case: 200 bars flat, prev slightly below EMA, last jumps above."""
    flat = [100.0] * 200
    dip_and_jump = [99.0, 105.0]  # prev=99 (<EMA=100), last=105 (>EMA)
    prices = flat + dip_and_jump

    enriched = _make_enriched(prices)
    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    ema_col = f"ema_{EMA_LONG}"
    assert prev["close"] < prev[ema_col] and last["close"] > last[ema_col]

    params = StrategyParams()
    score, reasons = score_trend(params, last, prev)
    assert any("kesti" in r and "yukar" in r for r in reasons), reasons
    assert score >= params.score_ema_initial_cross, score
