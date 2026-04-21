"""Market regime and multi-timeframe helpers for strategy scoring."""

from __future__ import annotations

from enum import Enum

import pandas as pd

from config import settings
from signal_models import SignalType


class MarketRegime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class TrendBias(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


def detect_regime(df: pd.DataFrame, lookback: int = 20) -> MarketRegime:
    """Infer the current market regime from trend indicators."""
    _ = lookback
    if df is None or len(df) < 50:
        return MarketRegime.UNKNOWN

    last = df.iloc[-1]
    adx = last.get("adx", 0)
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)
    close = float(last["close"])

    trend_adx = 20
    weak_adx = 15
    di_ratio = 1.25

    sma_20 = float(df["close"].tail(20).mean())
    momentum = (close - sma_20) / sma_20 * 100

    if adx >= trend_adx:
        if plus_di > minus_di * di_ratio:
            return MarketRegime.BULL
        if minus_di > plus_di * di_ratio:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    if adx >= weak_adx:
        if momentum > 3 and plus_di > minus_di:
            return MarketRegime.BULL
        if momentum < -3 and minus_di > plus_di:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    return MarketRegime.SIDEWAYS


def get_trend_bias(indicators, df: pd.DataFrame) -> TrendBias:
    """Determine higher-timeframe directional bias for MTF confluence."""
    if df is None or len(df) < 30:
        return TrendBias.NEUTRAL

    enriched = indicators.add_all(df.copy())
    regime = detect_regime(enriched)
    last = enriched.iloc[-1]
    close = float(last["close"])
    ema_long = last.get(f"ema_{settings.EMA_LONG}")
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)

    if regime == MarketRegime.BULL and pd.notna(ema_long) and close >= float(ema_long) and plus_di >= minus_di:
        return TrendBias.LONG
    if regime == MarketRegime.BEAR and pd.notna(ema_long) and close <= float(ema_long) and minus_di >= plus_di:
        return TrendBias.SHORT
    return TrendBias.NEUTRAL


def apply_confluence(signal_type: SignalType, trend_bias: TrendBias, reasons: list[str]) -> bool:
    """Validate multi-timeframe confluence for directional signals."""
    long_signals = {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}
    short_signals = {SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL}

    if signal_type in long_signals:
        if trend_bias != TrendBias.LONG:
            reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
            return False
        reasons.append("MTF confluence: günlük trend LONG, 15dk tetik destekliyor")
        return True

    if signal_type in short_signals:
        if trend_bias != TrendBias.SHORT:
            reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
            return False
        reasons.append("MTF confluence: günlük trend SHORT, 15dk tetik destekliyor")
        return True

    return True


def check_regime_persistence(df: pd.DataFrame, target_regime: MarketRegime, min_bars: int = 2) -> bool:
    """Check whether a target regime persisted for the latest bars."""
    if len(df) < min_bars + 1:
        return False
    for i in range(len(df) - min_bars, len(df)):
        sub = df.iloc[: i + 1]
        if detect_regime(sub) != target_regime:
            return False
    return True


def check_momentum_confirmation(df: pd.DataFrame, threshold: float = 4.0) -> bool:
    """Validate momentum when the primary trend signal is weak."""
    if len(df) < 20:
        return True
    last = df.iloc[-1]
    adx = last.get("adx", 0)
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)
    if adx >= 20:
        return True
    if abs(plus_di - minus_di) >= 5:
        return True
    sma_20 = float(df["close"].tail(20).mean())
    momentum = (float(last["close"]) - sma_20) / sma_20 * 100
    return abs(momentum) >= threshold
