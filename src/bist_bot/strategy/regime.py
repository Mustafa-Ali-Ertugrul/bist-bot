"""Market regime and multi-timeframe helpers for strategy scoring."""

from __future__ import annotations

from enum import Enum

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import SignalType


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
    """Determine higher-timeframe directional bias for MTF confluence.

    H6: When SMA20 slope and EMA200 slope point in opposite directions, the
    HTF bias is internally contradictory → return NEUTRAL (whipsaw guard).
    Uses H2's slope_lookback from settings (default 40).
    """
    if df is None or len(df) < 30:
        return TrendBias.NEUTRAL

    enriched = indicators.add_all(df.copy())
    regime = detect_regime(enriched)
    last = enriched.iloc[-1]
    close = float(last["close"])
    ema_long = last.get(f"ema_{settings.EMA_LONG}")
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)

    # H6: SMA20/EMA200 slope contradiction → NEUTRAL (no new params)
    mtf_block_enabled = getattr(settings, "MTF_CONFLUENCE_BLOCK_ENABLED", True)
    slope_lookback = getattr(settings, "SLOPE_LOOKBACK", 40)
    if (
        mtf_block_enabled
        and "sma_20" in enriched.columns
        and f"ema_{settings.EMA_LONG}" in enriched.columns
        and len(enriched) >= slope_lookback + 1
    ):
        sma_20_series = enriched["sma_20"]
        ema_long_series = enriched[f"ema_{settings.EMA_LONG}"]
        sma_20_slope = float(sma_20_series.iloc[-1]) - float(
            sma_20_series.iloc[-1 - slope_lookback]
        )
        ema_200_slope = float(ema_long_series.iloc[-1]) - float(
            ema_long_series.iloc[-1 - slope_lookback]
        )
        sma_20_dir = 1 if sma_20_slope > 0 else (-1 if sma_20_slope < 0 else 0)
        ema_200_dir = 1 if ema_200_slope > 0 else (-1 if ema_200_slope < 0 else 0)
        if sma_20_dir != 0 and ema_200_dir != 0 and sma_20_dir != ema_200_dir:
            return TrendBias.NEUTRAL

    if (
        regime == MarketRegime.BULL
        and pd.notna(ema_long)
        and close >= float(ema_long)
        and plus_di >= minus_di
    ):
        return TrendBias.LONG
    if (
        regime == MarketRegime.BEAR
        and pd.notna(ema_long)
        and close <= float(ema_long)
        and minus_di >= plus_di
    ):
        return TrendBias.SHORT
    return TrendBias.NEUTRAL


def apply_confluence(signal_type: SignalType, trend_bias: TrendBias, reasons: list[str]) -> bool:
    """Validate multi-timeframe confluence for directional signals."""
    long_signals = {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}
    short_signals = {SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL}

    if signal_type in long_signals:
        if trend_bias == TrendBias.LONG:
            reasons.append("MTF confluence: günlük trend LONG, 15dk tetik destekliyor")
            return True
        if trend_bias == TrendBias.NEUTRAL:
            reasons.append("MTF confluence zayıf: üst zaman dilimi nötr (RADAR adayı)")
        else:
            reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
        return False

    if signal_type in short_signals:
        if trend_bias == TrendBias.SHORT:
            reasons.append("MTF confluence: günlük trend SHORT, 15dk tetik destekliyor")
            return True
        if trend_bias == TrendBias.NEUTRAL:
            reasons.append("MTF confluence zayıf: üst zaman dilimi nötr (RADAR adayı)")
        else:
            reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
        return False

    return True


def check_regime_persistence(
    df: pd.DataFrame, target_regime: MarketRegime, min_bars: int = 2
) -> bool:
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


# ---------------------------------------------------------------------------
# Macro-level regime detection (Item 1)
# ---------------------------------------------------------------------------

MACRO_BENCHMARK_TICKERS = ("THYAO.IS", "GARAN.IS", "AKBNK.IS")
"""Tickers used as a lightweight proxy for the broader market regime."""


def detect_macro_regime(dfs: dict[str, pd.DataFrame]) -> MarketRegime:
    """Aggregate per-ticker regime into a single macro view.

    Returns ``MarketRegime.UNKNOWN`` when fewer than two benchmarks are
    available. The final decision is the *mode* of individual regimes, with
    a simple tie-break: BULL > SIDEWAYS > BEAR > UNKNOWN.
    """
    if not dfs:
        return MarketRegime.UNKNOWN

    regime_votes: list[MarketRegime] = []
    for _ticker, df in dfs.items():
        if df is None or len(df) < 50:
            continue
        regime_votes.append(detect_regime(df))

    if len(regime_votes) < 2:
        # Not enough data — fall back to the single available reading.
        return regime_votes[0] if regime_votes else MarketRegime.UNKNOWN

    from collections import Counter

    counts = Counter(regime_votes)
    # Deterministic tie-break order: BULL > SIDEWAYS > BEAR > UNKNOWN.
    # Invert so higher-priority regimes get a larger sort key.
    tie_break_scores = {
        MarketRegime.BULL: 4,
        MarketRegime.SIDEWAYS: 3,
        MarketRegime.BEAR: 2,
        MarketRegime.UNKNOWN: 1,
    }
    best = max(counts, key=lambda r: (counts[r], tie_break_scores.get(r, 0)))
    return best


def is_macro_bullish(dfs: dict[str, pd.DataFrame]) -> bool:
    """Return True when the macro regime is BULL or BEAR is absent."""
    regime = detect_macro_regime(dfs)
    return regime == MarketRegime.BULL


def is_macro_bearish(dfs: dict[str, pd.DataFrame]) -> bool:
    """Return True when the macro regime is BEAR."""
    return detect_macro_regime(dfs) == MarketRegime.BEAR
