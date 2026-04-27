"""Regression tests for MarketCandle schema and validate_dataframe."""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from bist_bot.data.schemas import MarketCandle, validate_dataframe


def _make_df_with_index(index_name: str | None = None) -> pd.DataFrame:
    """Create a valid OHLCV dataframe with a DatetimeIndex."""
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0, 13.0, 14.0],
            "high": [11.0, 12.0, 13.0, 14.0, 15.0],
            "low": [9.0, 10.0, 11.0, 12.0, 13.0],
            "close": [10.5, 11.5, 12.5, 13.5, 14.5],
            "volume": [100, 200, 300, 400, 500],
        },
        index=idx,
    )
    if index_name:
        df.index.name = index_name
    return df


def test_market_candle_valid():
    """A valid candle should construct without error."""
    c = MarketCandle(
        timestamp=pd.Timestamp("2025-01-01"),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=100,
    )
    assert c.open == 10.0
    assert c.volume == 100


def test_market_candle_rejects_zero_open():
    """open must be > 0."""
    with pytest.raises(ValidationError):
        MarketCandle(
            timestamp=pd.Timestamp("2025-01-01"),
            open=0.0,
            high=11.0,
            low=9.0,
            close=10.5,
            volume=100,
        )


def test_market_candle_rejects_negative_volume():
    """volume must be >= 0."""
    with pytest.raises(ValidationError):
        MarketCandle(
            timestamp=pd.Timestamp("2025-01-01"),
            open=10.0,
            high=11.0,
            low=9.0,
            close=10.5,
            volume=-5,
        )


def test_validate_dataframe_with_datetime_index_named_date():
    """Dataframe with DatetimeIndex named 'Date' should validate successfully."""
    df = _make_df_with_index("Date")
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 5
    assert "open" in result.columns


def test_validate_dataframe_with_datetime_index_named_date_lowercase():
    """Dataframe with DatetimeIndex named 'date' should validate successfully."""
    df = _make_df_with_index("date")
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 5


def test_validate_dataframe_with_datetime_index_no_name():
    """Dataframe with unnamed DatetimeIndex should validate successfully."""
    df = _make_df_with_index()
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 5


def test_validate_dataframe_with_date_column():
    """Dataframe with a 'date' column (not index) should validate successfully."""
    idx = pd.RangeIndex(5)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=5, freq="D"),
            "open": [10.0, 11.0, 12.0, 13.0, 14.0],
            "high": [11.0, 12.0, 13.0, 14.0, 15.0],
            "low": [9.0, 10.0, 11.0, 12.0, 13.0],
            "close": [10.5, 11.5, 12.5, 13.5, 14.5],
            "volume": [100, 200, 300, 400, 500],
        },
        index=idx,
    )
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 5


def test_validate_dataframe_drops_nan_rows():
    """Rows with all-NaN OHLCV should be dropped; remaining rows should validate."""
    df = _make_df_with_index()
    # Inject NaN rows
    df.iloc[1] = float("nan")
    df.iloc[3] = float("nan")
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 3


def test_validate_dataframe_all_nan_returns_none():
    """Dataframe with all NaN OHLCV should return None without raising."""
    df = _make_df_with_index()
    df["open"] = float("nan")
    df["high"] = float("nan")
    df["low"] = float("nan")
    df["close"] = float("nan")
    df["volume"] = float("nan")
    result = validate_dataframe(df, validate=True)
    assert result is None


def test_validate_dataframe_drops_zero_ohlcv():
    """Rows with zero open/high/low/close should be dropped."""
    df = _make_df_with_index()
    df.iloc[0, df.columns.get_loc("open")] = 0.0
    df.iloc[0, df.columns.get_loc("close")] = 0.0
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 4


def test_validate_dataframe_drops_negative_ohlcv():
    """Rows with negative open/high/low/close should be dropped."""
    df = _make_df_with_index()
    df.iloc[0, df.columns.get_loc("open")] = -1.0
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 4


def test_validate_dataframe_drops_negative_volume():
    """Rows with negative volume should be dropped."""
    df = _make_df_with_index()
    df.iloc[0, df.columns.get_loc("volume")] = -10
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 4


def test_validate_dataframe_false_path_drops_nan():
    """validate=False should also drop NaN rows."""
    df = _make_df_with_index()
    df.iloc[1] = float("nan")
    result = validate_dataframe(df, validate=False)
    assert result is not None
    assert len(result) == 4


def test_validate_dataframe_false_path_drops_invalid():
    """validate=False should drop rows with zero/negative OHLCV."""
    df = _make_df_with_index()
    df.iloc[0, df.columns.get_loc("open")] = 0.0
    result = validate_dataframe(df, validate=False)
    assert result is not None
    assert len(result) == 4


def test_validate_dataframe_none_input():
    """None input should return None."""
    assert validate_dataframe(None) is None


def test_validate_dataframe_empty():
    """Empty dataframe should return None."""
    df = pd.DataFrame()
    assert validate_dataframe(df) is None


def test_validate_dataframe_missing_columns():
    """Dataframe missing required columns should return None."""
    df = pd.DataFrame({"open": [10.0], "close": [11.0]})
    assert validate_dataframe(df) is None


def test_validate_dataframe_with_inf_values():
    """Rows with inf values should be treated as invalid and dropped."""
    import numpy as np

    df = _make_df_with_index()
    df.iloc[0, df.columns.get_loc("open")] = np.inf
    df.iloc[1, df.columns.get_loc("high")] = -np.inf
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert len(result) == 3
