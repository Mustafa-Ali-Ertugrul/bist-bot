"""Market data validation schemas using Pydantic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketCandle(BaseModel):
    """Pydantic model representing a single OHLCV candle for validation."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    timestamp: datetime
    open: float = Field(..., gt=0.0)
    high: float = Field(..., gt=0.0)
    low: float = Field(..., gt=0.0)
    close: float = Field(..., gt=0.0)
    volume: int | float = Field(default=0, ge=0)

    @field_validator("high")
    @classmethod
    def validate_high(cls, v: float, info: Any) -> float:
        if "open" in info.data and "low" in info.data:
            if v < info.data["low"]:
                raise ValueError("High must be >= low")
        return v

    @field_validator("low")
    @classmethod
    def validate_low(cls, v: float, info: Any) -> float:
        if "open" in info.data and "high" in info.data:
            if v > info.data["high"]:
                raise ValueError("Low must be <= high")
        return v


_TIMESTAMP_KEYS = {"index", "date", "Date", "datetime", "Datetime", "timestamp", "Timestamp"}


def _normalize_timestamp(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Extract and normalize a DatetimeIndex from df, handling various column names."""
    # If index is already a DatetimeIndex, use it
    if isinstance(df.index, pd.DatetimeIndex):
        return df.index

    # Check if any timestamp-like column exists
    for key in _TIMESTAMP_KEYS:
        if key in df.columns:
            return pd.DatetimeIndex(pd.to_datetime(df[key]))

    # Fallback: try to convert whatever the index is
    return pd.DatetimeIndex(pd.to_datetime(df.index))


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Replace inf with NaN, then drop rows with invalid OHLCV values."""
    df = df.copy()
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # Drop rows where any required OHLCV field is NaN
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    df = df.dropna(subset=ohlcv_cols)

    # Drop rows where open/high/low/close <= 0 or volume < 0
    mask = (
        (df["open"] > 0)
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
        & (df["volume"] >= 0)
    )
    return df.loc[mask].copy()


def validate_dataframe(df: pd.DataFrame | None, validate: bool = True) -> pd.DataFrame | None:
    """Validate a dataframe against the MarketCandle schema.

    If validate is True, it converts rows to MarketCandle objects briefly to ensure
    quality data, then back to a sanitized DataFrame.
    If False, it skips strict Pydantic checks and just drops NaNs.
    """
    if df is None or df.empty:
        return None

    df = cast(pd.DataFrame, df.copy())
    df.columns = [str(col).lower() for col in df.columns]

    required_cols = ["open", "high", "low", "close", "volume"]
    if not all(c in df.columns for c in required_cols):
        return None

    # Preserve timestamp column if it exists (e.g., "date" from reset_index)
    ts_col = None
    for key in _TIMESTAMP_KEYS:
        if key.lower() in df.columns:
            ts_col = key.lower()
            break

    # Keep timestamp column alongside OHLCV
    keep_cols = list(required_cols)
    if ts_col is not None:
        keep_cols.append(ts_col)

    df = cast(pd.DataFrame, df[keep_cols])

    # Normalize timestamp and set as index
    dt_index = _normalize_timestamp(df)
    df.index = dt_index.tz_localize(None)

    # Drop the timestamp column if it was a column (not the original index)
    if ts_col is not None and ts_col in df.columns:
        df = df.drop(columns=[ts_col])

    # Clean invalid rows before any validation
    df = _clean_ohlcv(df)

    if df.empty:
        return None

    # Fast path: just return cleaned data
    if not validate:
        return df

    # Strict path: validate via Pydantic
    try:
        dict_records = df.reset_index().to_dict(orient="records")
        for r in dict_records:
            # Map any index key to timestamp
            for key in _TIMESTAMP_KEYS:
                if key in r:
                    r["timestamp"] = r.pop(key)
                    break

        valid_candles = [MarketCandle(**r) for r in dict_records]

        if not valid_candles:
            return None

        valid_records = [c.model_dump() for c in valid_candles]
        clean_df = pd.DataFrame(valid_records)
        clean_df.set_index("timestamp", inplace=True)
        return clean_df
    except Exception as e:
        from bist_bot.app_logging import get_logger

        get_logger(__name__, component="schemas").error(
            "invalid_data_schema", error_type=type(e).__name__, details=str(e)
        )
        return None
