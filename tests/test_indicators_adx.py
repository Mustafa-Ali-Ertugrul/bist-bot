"""Tests for Wilder-style ATR and ADX calculations."""

from __future__ import annotations

import pandas as pd

from bist_bot.indicators import TechnicalIndicators


def build_ohlc_frame() -> pd.DataFrame:
    rows = []
    base = 100.0
    for idx in range(40):
        open_price = base + (idx * 0.6)
        close_price = open_price + 0.35 + ((idx % 3) * 0.05)
        rows.append(
            {
                "open": open_price,
                "high": close_price + 0.8,
                "low": open_price - 0.7,
                "close": close_price,
                "volume": 1000 + (idx * 15),
            }
        )
    return pd.DataFrame(rows)


def test_add_adx_produces_bounded_positive_value() -> None:
    df = build_ohlc_frame()

    df = TechnicalIndicators.add_atr(df, period=14)
    df = TechnicalIndicators.add_adx(df, period=14)

    latest_adx = df["adx"].dropna().iloc[-1]

    assert latest_adx > 0
    assert 0 <= latest_adx <= 100


def test_add_adx_computes_atr_when_missing_and_drops_temp_columns() -> None:
    df = build_ohlc_frame()

    result = TechnicalIndicators.add_adx(df, period=14)

    assert "atr" in result.columns
    assert "plus_dm" not in result.columns
    assert "minus_dm" not in result.columns
    assert result["adx"].dropna().iloc[-1] > 0


def test_add_rsi_uses_plain_string_zone_labels() -> None:
    df = build_ohlc_frame()

    df = TechnicalIndicators.add_rsi(df, period=14)

    populated = df.loc[df["rsi"].notna(), "rsi_zone"]
    assert populated.dtype == object
    assert populated.iloc[-1] in {
        "OVERSOLD",
        "NEAR_OVERSOLD",
        "NEUTRAL",
        "NEAR_OVERBOUGHT",
        "OVERBOUGHT",
    }


def test_add_rsi_preserves_unknown_for_unseeded_rows() -> None:
    df = build_ohlc_frame().head(5)

    df = TechnicalIndicators.add_rsi(df, period=14)

    assert set(df["rsi_zone"]) == {"UNKNOWN"}
