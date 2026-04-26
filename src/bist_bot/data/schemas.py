"""Market data validation schemas using Pydantic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

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


def validate_dataframe(df: pd.DataFrame | None, validate: bool = True) -> pd.DataFrame | None:
    """Validate a dataframe against the MarketCandle schema.

    If validate is True, it converts rows to MarketCandle objects briefly to ensure
    quality data, then back to a sanitized DataFrame.
    If False, it skips strict Pydantic checks and just drops NaNs.
    """
    if df is None or df.empty:
        return None

    # Force standard columns
    df = cast(pd.DataFrame, df.copy())
    df.columns = [str(col).lower() for col in df.columns]

    required_cols = ["open", "high", "low", "close", "volume"]
    if not all(c in df.columns for c in required_cols):
        return None

    df = cast(pd.DataFrame, df[required_cols])

    # Check index for timestamps
    if df.index.name is None and not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df.set_index("timestamp", inplace=True)

    df.index = pd.DatetimeIndex(pd.to_datetime(df.index)).tz_localize(None)

    # Fast path: just drop NAs and negative values via Pandas
    if not validate:
        df = cast(pd.DataFrame, df.dropna())
        return df[(df["open"] > 0) & (df["low"] > 0)].copy()

    # Strict boundary checks via Pydantic
    try:
        dict_records = df.reset_index().to_dict(orient="records")
        # Ensure the index column maps to timestamp
        for r in dict_records:
            if "index" in r:
                r["timestamp"] = r.pop("index")

        valid_candles = [MarketCandle(**r) for r in dict_records]

        # Convert back to dataframe
        valid_records = [c.model_dump() for c in valid_candles]
        clean_df = pd.DataFrame(valid_records)
        clean_df.set_index("timestamp", inplace=True)
        return clean_df
    except Exception as e:
        from bist_bot.app_logging import get_logger

        get_logger(__name__, component="schemas").error(
            "validation_failed", error_type=type(e).__name__, details=str(e)
        )
        return None
