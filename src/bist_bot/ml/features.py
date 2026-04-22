"""Shared feature construction for the signal meta-model."""

from __future__ import annotations

from typing import Any

import pandas as pd

from bist_bot.config.settings import settings


FEATURE_COLUMNS = [
    "score",
    "adx",
    "rsi",
    "volume_ratio",
    "atr_pct",
    "risk_reward_ratio",
    "volatility_scale",
    "correlation_scale",
    "trend_bias",
    "close_vs_ema_long",
]


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_feature_payload(
    row: pd.Series,
    *,
    score: float,
    stop_loss: float,
    target_price: float,
    volatility_scale: float = 1.0,
    correlation_scale: float = 1.0,
    trend_bias: float | None = None,
) -> dict[str, float]:
    close_price = to_float(row.get("close"))
    ema_long = to_float(row.get(f"ema_{settings.EMA_LONG}"), close_price)
    risk_per_share = max(close_price - stop_loss, close_price * 0.01)
    reward_per_share = max(target_price - close_price, 0.0)
    reward_to_risk_ratio = (
        reward_per_share / risk_per_share if risk_per_share > 0 else 0.0
    )
    inferred_bias = 1.0 if score > 0 else -1.0 if score < 0 else 0.0
    return {
        "score": float(score),
        "adx": to_float(row.get("adx")),
        "rsi": to_float(row.get("rsi")),
        "volume_ratio": to_float(row.get("volume_ratio")),
        "atr_pct": to_float(row.get("atr")) / close_price if close_price > 0 else 0.0,
        "risk_reward_ratio": reward_to_risk_ratio,
        "volatility_scale": float(volatility_scale),
        "correlation_scale": float(correlation_scale),
        "trend_bias": inferred_bias if trend_bias is None else float(trend_bias),
        "close_vs_ema_long": (close_price / ema_long) - 1.0 if ema_long > 0 else 0.0,
    }
