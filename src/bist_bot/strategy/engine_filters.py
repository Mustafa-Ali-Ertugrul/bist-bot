"""Signal classification and filtering helpers for StrategyEngine."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import (
    MarketRegime,
    TrendBias,
    apply_confluence,
    check_momentum_confirmation,
    detect_regime,
)
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="strategy")

ScoreTwoRows = Callable[[pd.Series, pd.Series], tuple[float, list[str]]]
TrendScorer = Callable[[pd.Series, pd.Series, pd.DataFrame | None], tuple[float, list[str]]]
ScoreOneRow = Callable[[pd.Series], tuple[float, list[str]]]
MomentumChecker = Callable[[pd.DataFrame, float], bool]
ConfluenceApplier = Callable[[SignalType, TrendBias, list[str]], bool]
RejectLogger = Callable[..., None]


def component_direction(score: float) -> int:
    """Return the directional sign of a score component."""
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def _has_mtf_slope_contradiction(params: StrategyParams, df: pd.DataFrame) -> bool:
    if not params.mtf_confluence_block_enabled:
        return False
    ema_column = f"ema_{settings.EMA_LONG}"
    lookback = max(int(params.slope_lookback), 1)
    if len(df) < lookback + 1 or "sma_20" not in df.columns or ema_column not in df.columns:
        return False
    sma_slope = float(df["sma_20"].iloc[-1]) - float(df["sma_20"].iloc[-1 - lookback])
    ema_slope = float(df[ema_column].iloc[-1]) - float(df[ema_column].iloc[-1 - lookback])
    sma_dir = component_direction(sma_slope)
    ema_dir = component_direction(ema_slope)
    return sma_dir != 0 and ema_dir != 0 and sma_dir != ema_dir


def _apply_chase_cap(
    params: StrategyParams,
    last: pd.Series,
    score: float,
    *,
    trend_dir: int,
    momentum_dir: int,
    reasons: list[str],
) -> float:
    if not params.chase_block_enabled or score == 0:
        return score
    bb_position = str(last.get("bb_position", ""))
    cci = float(last.get("cci", 0.0) or 0.0)
    distance_resistance = float(last.get("dist_to_resistance_pct", float("inf")) or 0.0)
    distance_support = float(last.get("dist_to_support_pct", float("inf")) or 0.0)
    long_overextended = score > 0 and (
        bb_position == "ABOVE_UPPER" or cci >= 150 or distance_resistance <= 1.0
    )
    short_overextended = score < 0 and (
        bb_position == "BELOW_LOWER" or cci <= -150 or distance_support <= 1.0
    )
    if not (long_overextended or short_overextended):
        return score
    adx = float(last.get("adx", 0.0) or 0.0)
    score_dir = component_direction(score)
    strong_trend_ride = adx >= 30.0 and trend_dir == score_dir and momentum_dir == score_dir
    cap = params.chase_strong_trend_cap if strong_trend_ride else params.chase_blocked_score_cap
    capped = min(score, cap) if score > 0 else max(score, -cap)
    if strong_trend_ride:
        reasons.append(f"Güçlü trend ride → skor {cap:g} ile sınırlandı")
    direction = "uzun" if score > 0 else "kısa"
    reasons.append(f"Aşırı uzama chase koruması → {direction} skor {cap:g} ile sınırlandı")
    return capped


def is_buy_signal(signal_type: SignalType) -> bool:
    """Return whether a signal opens or adds a long position."""
    return signal_type in {
        SignalType.STRONG_BUY,
        SignalType.BUY,
        SignalType.WEAK_BUY,
    }


def classify_signal(
    params: StrategyParams,
    score: float,
    agreement_ratio: float | None = None,
) -> tuple[SignalType, str]:
    """Map a bounded numeric score to a signal type and confidence key."""
    if agreement_ratio is None:
        confidence = None
    elif agreement_ratio >= 0.75:
        confidence = "confidence.high"
    elif agreement_ratio >= 0.5:
        confidence = "confidence.medium"
    else:
        confidence = "confidence.low"
    if score >= params.strong_buy_threshold:
        return SignalType.STRONG_BUY, confidence or "confidence.high"
    if score >= params.buy_threshold:
        return SignalType.BUY, confidence or "confidence.medium"
    if score >= params.weak_buy_threshold:
        return SignalType.WEAK_BUY, confidence or "confidence.low"
    if score <= params.strong_sell_threshold:
        return SignalType.STRONG_SELL, confidence or "confidence.high"
    if score <= params.sell_threshold:
        return SignalType.SELL, confidence or "confidence.medium"
    if score <= params.weak_sell_threshold:
        return SignalType.WEAK_SELL, confidence or "confidence.low"
    return SignalType.HOLD, confidence or "confidence.low"


def get_valid_adx(params: StrategyParams, ticker: str, last: pd.Series) -> float | None:
    """Extract a valid ADX value from the last row, or None if missing/non-numeric/NaN."""
    _ = params  # kept for API consistency with passes_adx_filter
    adx_raw = last.get("adx")
    try:
        adx = float(adx_raw)
    except (TypeError, ValueError):
        logger.debug("strategy_adx_missing_type", ticker=ticker)
        return None
    if not pd.notna(adx):
        logger.debug("strategy_adx_missing_nan", ticker=ticker)
        return None
    return adx


def passes_adx_filter(params: StrategyParams, ticker: str, last: pd.Series) -> bool:
    """Reject rows where ADX is missing or NaN.

    Valid ADX below threshold is no longer rejected here;
    a soft penalty is applied later in the scoring pipeline.
    """
    return get_valid_adx(params, ticker, last) is not None


def apply_low_adx_penalty(
    params: StrategyParams, adx: float, score: float, reasons: list[str]
) -> tuple[float, list[str]]:
    """Apply a soft penalty when ADX is below the trend threshold.

    The penalty moves the score toward zero rather than rejecting the ticker.
    """
    if adx >= params.adx_threshold:
        return score, reasons
    penalty = params.adx_low_trend_penalty
    if score > 0:
        score -= penalty
    elif score < 0:
        score += penalty
    reasons.append(f"ADX düşük ({adx:.1f}) → trend zayıf, skor cezası")
    return score, reasons


def calculate_score_and_reasons(
    params: StrategyParams,
    ticker: str,
    df: pd.DataFrame,
    *,
    last: pd.Series,
    prev: pd.Series,
    momentum_scorer: ScoreTwoRows,
    trend_scorer: TrendScorer,
    volume_scorer: ScoreTwoRows,
    structure_scorer: ScoreOneRow,
    momentum_checker: MomentumChecker = check_momentum_confirmation,
    reject_logger: RejectLogger | None = None,
) -> tuple[float, list[str], float | None] | None:
    """Calculate the bounded strategy score and explanatory reason list."""
    reasons: list[str] = []
    regime = detect_regime(df)
    if _has_mtf_slope_contradiction(params, df):
        regime = MarketRegime.SIDEWAYS
        reasons.append("MTF çelişki: SMA20 ve EMA200 eğimleri zıt")
    if regime == MarketRegime.SIDEWAYS:
        reasons.append("Piyasa rejimi yatay - skor etkisi azaltildi")

    s1, r1 = momentum_scorer(last, prev)
    s2, r2 = trend_scorer(last, prev, df)
    s3, r3 = volume_scorer(last, prev)
    s4, r4 = structure_scorer(last)
    reasons.extend(r1 + r2 + r3 + r4)

    raw_score = s1 + s2 + s3 + s4
    trend_dir = component_direction(s2)
    momentum_dir = component_direction(s1)
    raw_dir = component_direction(raw_score)
    counter_trend_multiplier = float(params.counter_trend_multiplier)
    if (
        trend_dir != 0
        and momentum_dir != 0
        and trend_dir != momentum_dir
        and raw_dir != 0
        and raw_dir != trend_dir
        and counter_trend_multiplier != 1.0
    ):
        s1 *= counter_trend_multiplier
        trend_label = "yukarı" if trend_dir > 0 else "aşağı"
        reasons.append(
            "Karşıt-trend bastırma uygulandı "
            f"(trend {trend_label}, momentum x{counter_trend_multiplier:g})"
        )

    score = s1 + s2 + s3 + s4
    score = _apply_chase_cap(
        params,
        last,
        score,
        trend_dir=trend_dir,
        momentum_dir=momentum_dir,
        reasons=reasons,
    )
    _components = (s1, s2, s3, s4)
    agree = sum(1 for c in _components if (score > 0 and c > 0) or (score < 0 and c < 0))
    agreement_ratio = agree / 4.0

    if regime == MarketRegime.SIDEWAYS:
        score *= params.sideways_score_multiplier
        if abs(score) < params.buy_threshold:
            logger.debug(
                "strategy_sideways_filtered",
                ticker=ticker,
                score=round(float(score), 2),
            )
            if reject_logger is not None:
                reject_logger(
                    stage="scoring",
                    reason_code="score_filtered_sideways",
                    score=round(float(score), 2),
                    reason_detail="sideways regime score stayed below buy threshold",
                )
            return None

    if score != 0 and not momentum_checker(df, params.momentum_confirmation_threshold):
        if score < 0 or abs(score) < params.buy_threshold + params.sideways_extra_threshold:
            logger.debug(
                "strategy_momentum_filtered",
                ticker=ticker,
                score=round(float(score), 2),
            )
            if reject_logger is not None:
                reject_logger(
                    stage="scoring",
                    reason_code="score_filtered_momentum",
                    score=round(float(score), 2),
                    reason_detail="momentum confirmation failed near buy threshold",
                )
            return None

    # H4 — OBV / volume divergence gate.
    # Raw volume spike can pad the volume score (vol_confirm +8, vol_spike +8, total +16)
    # even when OBV is DOWN or price_volume is BEARISH_CONFIRMATION (structural
    # distribution). Without this gate, an institutional exit + retail chase produces a
    # fake long signal. Override (min/max), NOT penalty — H7 saturation owns penalty.
    # Also symmetric for shorts (OBV UP / BULLISH_CONFIRMATION against short candidates).
    if params.obv_divergence_block_enabled:
        obv_trend = last.get("obv_trend", "FLAT")
        pv_direction = last.get("price_volume_direction", "NONE")
        obv_down = obv_trend == "DOWN"
        bearish_pv = pv_direction == "BEARISH_CONFIRMATION"
        volume_divergence_long = obv_down or bearish_pv
        obv_up = obv_trend == "UP"
        bullish_pv = pv_direction == "BULLISH_CONFIRMATION"
        volume_divergence_short = obv_up or bullish_pv
        cap = params.obv_divergence_cap

        if volume_divergence_long and score > 0:
            capped = min(score, cap)
            if capped != score:
                reasons.append(
                    f"Hacim divergence (OBV düşüş / fiyat-hacim ayı) → uzun skor {cap:.0f}'e bastırıldı"
                )
                logger.debug(
                    "strategy_obv_divergence_capped_long",
                    ticker=ticker,
                    old_score=round(float(score), 2),
                    capped_score=round(float(capped), 2),
                    cap=cap,
                    obv_trend=obv_trend,
                    pv_direction=pv_direction,
                )
            score = capped
        elif volume_divergence_short and score < 0:
            capped = max(score, -cap)
            if capped != score:
                reasons.append(
                    f"Hacim divergence (OBV yükseliş / fiyat-hacim boğa) → kısa skor -{cap:.0f}'e bastırıldı"
                )
                logger.debug(
                    "strategy_obv_divergence_capped_short",
                    ticker=ticker,
                    old_score=round(float(score), 2),
                    capped_score=round(float(capped), 2),
                    cap=cap,
                    obv_trend=obv_trend,
                    pv_direction=pv_direction,
                )
            score = capped

    if params.agreement_gate_enabled and agreement_ratio < params.agreement_gate_threshold:
        cap = float(params.agreement_low_cap)
        capped = max(-cap, min(cap, score))
        if capped != score:
            reasons.append(
                f"Bileşen uyumu düşük ({agreement_ratio:.2f}) → skor {cap:g} ile sınırlandı"
            )
        score = capped

    score = max(-100, min(100, score))
    if score == 0:
        if reject_logger is not None:
            reject_logger(
                stage="scoring",
                reason_code="score_zero_after_penalty",
                score=0.0,
                reason_detail="combined component score resolved to zero",
            )
        return None
    return score, reasons, agreement_ratio


def passes_multi_timeframe_confluence(
    ticker: str,
    *,
    signal: Signal,
    trend_bias: TrendBias,
    multi_timeframe: bool,
    confluence_applier: ConfluenceApplier = apply_confluence,
    reject_logger: RejectLogger | None = None,
) -> bool:
    """Apply trend/trigger confluence when multi-timeframe mode is active."""
    if not (multi_timeframe and getattr(settings, "MTF_ENABLED", True)):
        return True
    if confluence_applier(signal.signal_type, trend_bias, signal.reasons):
        return True
    logger.debug("strategy_mtf_filtered", ticker=ticker)
    if reject_logger is not None:
        reject_logger(
            stage="mtf",
            reason_code="mtf_confluence_blocked",
            score=round(float(signal.score), 2),
            signal_type=signal.signal_type.name,
            trend_bias=trend_bias.value,
            reason_detail=f"trend_bias {trend_bias.value} vs signal {signal.signal_type.name}",
        )
    return False
