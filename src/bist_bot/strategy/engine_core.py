"""Core dataframe preparation helpers for strategy analysis."""

from __future__ import annotations

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.regime import TrendBias, get_trend_bias


def extract_timeframes(
    market_data: pd.DataFrame | dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """Return trend and trigger frames from single or multi-timeframe input."""
    if isinstance(market_data, dict):
        trend_df = market_data.get("trend")
        trigger_df = market_data.get("trigger")
        if trend_df is None or trigger_df is None:
            raise ValueError("Multi-timeframe veri 'trend' ve 'trigger' anahtarlarini icermeli")
        return trend_df, trigger_df, True
    return market_data, market_data, False


def prepare_analysis_frame(
    indicators: TechnicalIndicators,
    trigger_df: pd.DataFrame,
    *,
    trend_df: pd.DataFrame,
    multi_timeframe: bool,
) -> tuple[pd.DataFrame, TrendBias, pd.Series, pd.Series]:
    """Enrich trigger data and extract current/previous scoring rows."""
    if trigger_df.empty or len(trigger_df) < 2:
        raise ValueError("Trigger veri setinde analiz için yeterli satir yok")
    analysis_df = indicators.add_all(trigger_df.copy())
    if analysis_df.empty or len(analysis_df) < 2:
        raise ValueError("Indikator hesaplamasi sonrasi yeterli veri kalmadi")
    trend_bias = (
        get_trend_bias(indicators, trend_df)
        if multi_timeframe and getattr(settings, "MTF_ENABLED", True)
        else TrendBias.NEUTRAL
    )
    last = analysis_df.iloc[-1].copy()
    prev = analysis_df.iloc[-2]
    return analysis_df, trend_bias, last, prev
