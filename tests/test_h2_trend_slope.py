"""H2 slope filter tests for score_trend.

Verifies that EMA200-based trend confirmation now requires
both price level AND EMA200 slope direction.
Sahte trend dönüşleri (fiyat EMA200 üstünde ama EMA200 düşen)
now filter out the trend confirmation score.

sweep sonucu (results/walk_forward_bist30_h2_sl*.csv):
  sl=5 base median 0.00 → çöküş, varsayılan 40'e yükseltildi.
  sl=40: WF median 0.99, overfit 53.6%, robust 5, stress 0.53 → dört kriteri geçti → default.
  sl=20: overfit %46.4 ama stress 0.48 < 0.5 → kural gereği reddedildi.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pandas as pd  # noqa: E402

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.scoring import score_trend  # noqa: E402

EMA_LONG = settings.EMA_LONG
EMA_COL = f"ema_{EMA_LONG}"
SLOPE_LOOKBACK = 5


def _build_frame(
    n: int = 45,
    *,
    ema_start: float = 90.0,
    ema_slope: float = 0.5,
    price_offset: float = 10.0,
    adx: float = 25.0,
) -> pd.DataFrame:
    """Build a frame with linear EMA and constant offset price."""
    rows = []
    for i in range(n):
        ema_val = ema_start + i * ema_slope
        rows.append(
            {
                "close": ema_val + price_offset,
                EMA_COL: ema_val,
                "adx": adx,
            }
        )
    return pd.DataFrame(rows)


def test_h2_positive_slope_above_ema_confirms_trend():
    """price > EMA200 + slope > 0 → trend teyit VAR (score_ema_cross eklenir)."""
    df = _build_frame(ema_slope=0.5, price_offset=10.0)
    params = StrategyParams(slope_lookback=SLOPE_LOOKBACK)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score, reasons = score_trend(params, last, prev, df)

    assert score > 0, f"Expected positive score for bullish trend confirmation, got {score}"
    assert any("yükseliş trendi" in r and "eğim pozitif" in r for r in reasons), (
        f"Expected positive-slope trend confirmation reason, got: {reasons}"
    )


def test_h2_negative_slope_above_ema_filters_fake_reversal():
    """price > EMA200 + slope < 0 → trend teyit YOK (sahte dönüş filtrelendi)."""
    df = _build_frame(ema_slope=-0.5, price_offset=10.0)
    params = StrategyParams(slope_lookback=SLOPE_LOOKBACK)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score, reasons = score_trend(params, last, prev, df)

    assert score == 0.0, (
        f"Expected zero trend-confirmation score for fake reversal (above EMA + negative slope), got {score}"
    )
    assert any("trend teyit yok" in r and "sahte dönüş filtresi" in r for r in reasons), (
        f"Expected fake-reversal filter reason, got: {reasons}"
    )


def test_h2_negative_slope_below_ema_confirms_downtrend():
    """price < EMA200 + slope < 0 → düşüş teyit VAR (simetri)."""
    df = _build_frame(ema_slope=-0.5, price_offset=-10.0)
    params = StrategyParams(slope_lookback=SLOPE_LOOKBACK)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score, reasons = score_trend(params, last, prev, df)

    assert score < 0, f"Expected negative score for downtrend confirmation, got {score}"
    assert any("düşüş teyiti" in r for r in reasons), (
        f"Expected downtrend confirmation reason, got: {reasons}"
    )


def test_h2_positive_slope_below_ema_no_downtrend_confirm():
    """price < EMA200 + slope > 0 → düşüş teyit YOK."""
    df = _build_frame(ema_slope=0.5, price_offset=-10.0)
    params = StrategyParams(slope_lookback=SLOPE_LOOKBACK)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score, reasons = score_trend(params, last, prev, df)

    assert score == 0.0, (
        f"Expected zero score for no downtrend confirmation (below EMA + positive slope), got {score}"
    )
    assert not any("düşüş teyiti" in r for r in reasons), (
        f"Should not have downtrend confirmation reason, got: {reasons}"
    )


def test_h2_insufficient_bars_fallback_level_based():
    """yetersiz bar (slope NaN) → seviye-bazlı fallback, crash yok."""
    df = _build_frame(
        n=3, ema_slope=0.5, price_offset=10.0
    )  # only 3 rows, slope_lookback=5 needs 6
    params = StrategyParams(slope_lookback=SLOPE_LOOKBACK)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score, reasons = score_trend(params, last, prev, df)

    assert score > 0, f"Expected fallback level-based score > 0, got {score}"
    assert any("yükseliş trendi" in r for r in reasons), (
        f"Expected level-based trend reason fallback, got: {reasons}"
    )
    assert any("slope yetersiz veri" in r for r in reasons), (
        f"Expected 'slope yetersiz veri' fallback note, got: {reasons}"
    )


def test_h2_slope_lookback_parameter_effect():
    """slope_lookback parametresi çalışır (5 vs 10 farklı sonuç verebilir)."""
    # Frame with short positive slope near the end but different longer slopes
    rows = []
    for i in range(30):
        ema_val = 90.0 + i * 0.3
        rows.append({"close": ema_val + 10.0, EMA_COL: ema_val, "adx": 25.0})
    df = pd.DataFrame(rows)
    params_5 = StrategyParams(slope_lookback=5)
    params_10 = StrategyParams(slope_lookback=10)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    score_5, _reasons_5 = score_trend(params_5, last, prev, df)
    score_10, _reasons_10 = score_trend(params_10, last, prev, df)

    # Both should confirm trend (positive slope in both windows)
    assert score_5 > 0, f"slope_lookback=5 should confirm trend, got score={score_5}"
    assert score_10 > 0, f"slope_lookback=10 should confirm trend, got score={score_10}"

    # The slope magnitude differs with different lookback windows
    slope_5 = df[EMA_COL].iloc[-1] - df[EMA_COL].iloc[-1 - 5]
    slope_10 = df[EMA_COL].iloc[-1] - df[EMA_COL].iloc[-1 - 10]
    # With linear EMA, slope_10 = 2 * slope_5, so the scores should be the same
    # (both pass the > 0 threshold) but the reason text should reference the slope correctly
    assert slope_10 > slope_5 > 0


def test_h2_no_df_backward_compatible():
    """score_trend without df arg still works (backward compat)."""
    df = _build_frame(ema_slope=0.5, price_offset=10.0)
    params = StrategyParams(slope_lookback=SLOPE_LOOKBACK)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Without df, defaults to level-based behavior (NaN slope → else branch)
    score, reasons = score_trend(params, last, prev)

    assert score > 0, f"Expected positive score with no df (backward compat), got {score}"
    assert any("yükseliş trendi" in r for r in reasons), f"Expected trend reason, got: {reasons}"


def test_h2_default_slope_lookback_40_with_45_bars():
    """Default slope_lookback=40 works with 45-bar frame (no NaN fallback)."""
    df = _build_frame(ema_slope=0.3, price_offset=10.0)  # 45 rows, default slope_lookback=40
    params = StrategyParams()  # slope_lookback=40 by default
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Rising EMA + price above → trend confirmation should work
    score, reasons = score_trend(params, last, prev, df)
    assert score > 0, (
        f"Default slope_lookback=40 should confirm trend (rising EMA+above), got {score}"
    )
    assert any("eğim pozitif" in r for r in reasons), (
        f"Expected positive-slope reason with default slope_lookback=40, got: {reasons}"
    )
