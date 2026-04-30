"""Tests for NaN-safe market summary, RSI inf guard, and ADX soft penalty."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.engine_filters import (
    apply_low_adx_penalty,
    get_valid_adx,
    passes_adx_filter,
)

# ---------------------------------------------------------------------------
# Part 1: get_market_summary NaN safety
# ---------------------------------------------------------------------------


def _make_df_with_rsi(rsi_value, vol_ratio=1.0, rows=35):
    """Build a minimal DataFrame that add_all can process, with a specific last RSI."""
    rows_data = []
    for i in range(rows):
        rows_data.append(
            {
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.0 + i,
                "volume": 1000.0,
            }
        )
    df = pd.DataFrame(rows_data)
    df.index = pd.date_range("2024-01-01", periods=rows, freq="1h")
    return df


def test_get_market_summary_ignores_nan_rsi():
    """get_market_summary should never return NaN for avg_rsi even when RSI is NaN."""
    from bist_bot.ui.runtime_data import get_market_summary

    mock_signal = MagicMock()
    mock_signal.ticker = "TEST.IS"

    df = _make_df_with_rsi(50.0)
    all_data = {"TEST.IS": df}

    with patch.object(
        TechnicalIndicators,
        "add_all",
        return_value=pd.DataFrame({"rsi": [float("nan")] * 35, "volume_ratio": [1.0] * 35}),
    ):
        result = get_market_summary([mock_signal], all_data)

    assert not math.isnan(result["avg_rsi"]), f"avg_rsi is NaN: {result}"
    assert result["avg_rsi"] == 50.0


def test_get_market_summary_ignores_nan_inf_volume_ratio():
    """get_market_summary should never return NaN for avg_vol_ratio even when volume_ratio has NaN/inf."""
    from bist_bot.ui.runtime_data import get_market_summary

    mock_signal = MagicMock()
    mock_signal.ticker = "TEST.IS"

    df = _make_df_with_rsi(50.0)
    all_data = {"TEST.IS": df}

    with patch.object(
        TechnicalIndicators,
        "add_all",
        return_value=pd.DataFrame({"rsi": [50.0] * 35, "volume_ratio": [float("inf")] * 35}),
    ):
        result = get_market_summary([mock_signal], all_data)

    assert not math.isnan(result["avg_vol_ratio"]), f"avg_vol_ratio is NaN: {result}"
    assert result["avg_vol_ratio"] == 1.0


def test_get_market_summary_total_analyzed_counts_non_empty_dataframes():
    """total_analyzed should count non-empty processed DataFrames, not just len(rsi_values)."""
    from bist_bot.ui.runtime_data import get_market_summary

    mock_signal = MagicMock()
    mock_signal.ticker = "TEST.IS"

    df1 = _make_df_with_rsi(50.0)
    df2 = _make_df_with_rsi(60.0)
    all_data = {"A.IS": df1, "B.IS": df2}

    with patch.object(
        TechnicalIndicators,
        "add_all",
        side_effect=lambda df: pd.DataFrame(
            {"rsi": [50.0] * len(df), "volume_ratio": [1.0] * len(df)}
        ),
    ):
        result = get_market_summary([mock_signal], all_data)

    assert result["total_analyzed"] == 2
    assert result["rsi_sample_count"] == 2


# ---------------------------------------------------------------------------
# Part 2: RSI inf guard in indicators.py
# ---------------------------------------------------------------------------


def test_add_rsi_replaces_inf_with_nan_and_clips():
    """add_rsi should replace inf in rs with NaN, and clip finite RSI to [0, 100]."""
    ti = TechnicalIndicators()
    rows = []
    for _i in range(30):
        rows.append(
            {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    df = pd.DataFrame(rows)
    df.index = pd.date_range("2024-01-01", periods=30, freq="1h")

    result = ti.add_rsi(df)

    assert "rsi" in result.columns
    finite_rsi = result["rsi"].replace([np.inf, -np.inf], np.nan).dropna()
    if len(finite_rsi) > 0:
        assert finite_rsi.min() >= 0.0, f"RSI below 0: {finite_rsi.min()}"
        assert finite_rsi.max() <= 100.0, f"RSI above 100: {finite_rsi.max()}"
    assert not result["rsi"].isin([np.inf, -np.inf]).any(), "RSI contains inf values"


def test_add_rsi_monotonic_rise_produces_rsi_100():
    """When price only rises, avg_loss=0, rs=inf, RSI should be clipped to 100."""
    ti = TechnicalIndicators()
    rows = []
    for i in range(30):
        rows.append(
            {
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.0 + i,
                "volume": 1000.0,
            }
        )
    df = pd.DataFrame(rows)
    df.index = pd.date_range("2024-01-01", periods=30, freq="1h")

    result = ti.add_rsi(df)

    last_rsi = result["rsi"].iloc[-1]
    assert pd.notna(last_rsi), "RSI should not be NaN for monotonically rising prices"
    assert last_rsi == 100.0, f"Expected RSI=100 for all-gains, got {last_rsi}"


# ---------------------------------------------------------------------------
# Part 3: ADX soft penalty
# ---------------------------------------------------------------------------


def _make_params(**overrides):
    defaults = dict(
        adx_threshold=20.0,
        adx_low_trend_penalty=5.0,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_adx_nan_still_rejects_ticker():
    """NaN ADX should still cause passes_adx_filter to return False."""
    params = _make_params()
    last = pd.Series({"adx": float("nan")})
    assert passes_adx_filter(params, "TEST.IS", last) is False


def test_adx_missing_non_numeric_still_rejects_ticker():
    """Missing or non-numeric ADX should still cause passes_adx_filter to return False."""
    params = _make_params()

    last_missing = pd.Series({"something_else": 42.0})
    assert passes_adx_filter(params, "TEST.IS", last_missing) is False

    last_string = pd.Series({"adx": "not_a_number"})
    assert passes_adx_filter(params, "TEST.IS", last_string) is False


def test_adx_below_threshold_no_longer_rejects_ticker():
    """Valid ADX below threshold should now pass the filter (penalty applied later)."""
    params = _make_params(adx_threshold=20.0)
    last = pd.Series({"adx": 12.0})
    assert passes_adx_filter(params, "TEST.IS", last) is True


def test_adx_below_threshold_applies_penalty_toward_zero():
    """Low ADX should apply a soft penalty that moves score toward zero."""
    params = _make_params(adx_threshold=20.0, adx_low_trend_penalty=5.0)

    score, reasons = apply_low_adx_penalty(params, adx=12.0, score=25.0, reasons=[])
    assert score == 20.0
    assert any("ADX düşük" in r for r in reasons)

    score2, reasons2 = apply_low_adx_penalty(params, adx=12.0, score=-25.0, reasons=[])
    assert score2 == -20.0
    assert any("ADX düşük" in r for r in reasons2)


def test_adx_above_threshold_applies_no_penalty():
    """ADX at or above threshold should not apply any penalty."""
    params = _make_params(adx_threshold=20.0, adx_low_trend_penalty=5.0)

    score, reasons = apply_low_adx_penalty(params, adx=25.0, score=25.0, reasons=[])
    assert score == 25.0
    assert len(reasons) == 0


def test_get_valid_adx_returns_float_for_valid_adx():
    """get_valid_adx should return a float for valid ADX values."""
    params = _make_params()
    last = pd.Series({"adx": 25.0})
    assert get_valid_adx(params, "TEST.IS", last) == 25.0


def test_get_valid_adx_returns_none_for_nan():
    """get_valid_adx should return None for NaN ADX."""
    params = _make_params()
    last = pd.Series({"adx": float("nan")})
    assert get_valid_adx(params, "TEST.IS", last) is None
