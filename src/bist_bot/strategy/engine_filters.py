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
ScoreOneRow = Callable[[pd.Series], tuple[float, list[str]]]
MomentumChecker = Callable[[pd.DataFrame, float], bool]
ConfluenceApplier = Callable[[SignalType, TrendBias, list[str]], bool]


def is_buy_signal(signal_type: SignalType) -> bool:
    """Return whether a signal opens or adds a long position."""
    return signal_type in {
        SignalType.STRONG_BUY,
        SignalType.BUY,
        SignalType.WEAK_BUY,
    }


def classify_signal(params: StrategyParams, score: float) -> tuple[SignalType, str]:
    """Map a bounded numeric score to a signal type and confidence key."""
    if score >= params.strong_buy_threshold:
        return SignalType.STRONG_BUY, "confidence.high"
    if score >= params.buy_threshold:
        return SignalType.BUY, "confidence.medium"
    if score >= params.weak_buy_threshold:
        return SignalType.WEAK_BUY, "confidence.low"
    if score <= params.strong_sell_threshold:
        return SignalType.STRONG_SELL, "confidence.high"
    if score <= params.sell_threshold:
        return SignalType.SELL, "confidence.medium"
    if score <= params.weak_sell_threshold:
        return SignalType.WEAK_SELL, "confidence.low"
    return SignalType.HOLD, "confidence.low"


def passes_adx_filter(params: StrategyParams, ticker: str, last: pd.Series) -> bool:
    """Reject rows where ADX is missing or below the configured threshold."""
    adx_raw = last.get("adx")
    try:
        adx = float(adx_raw)
    except (TypeError, ValueError):
        logger.debug("strategy_adx_missing_type", ticker=ticker)
        return False

    if not pd.notna(adx):
        logger.debug("strategy_adx_missing_nan", ticker=ticker)
        return False

    if adx >= params.adx_threshold:
        return True
    logger.debug("strategy_adx_filtered", ticker=ticker, adx=round(float(adx), 2))
    return False


def calculate_score_and_reasons(
    params: StrategyParams,
    ticker: str,
    df: pd.DataFrame,
    *,
    last: pd.Series,
    prev: pd.Series,
    momentum_scorer: ScoreTwoRows,
    trend_scorer: ScoreTwoRows,
    volume_scorer: ScoreOneRow,
    structure_scorer: ScoreOneRow,
    momentum_checker: MomentumChecker = check_momentum_confirmation,
) -> tuple[float, list[str]] | None:
    """Calculate the bounded strategy score and explanatory reason list."""
    reasons: list[str] = []
    regime = detect_regime(df)
    if regime == MarketRegime.SIDEWAYS:
        reasons.append("Piyasa rejimi yatay - skor etkisi azaltildi")

    s1, r1 = momentum_scorer(last, prev)
    s2, r2 = trend_scorer(last, prev)
    s3, r3 = volume_scorer(last)
    s4, r4 = structure_scorer(last)
    score = s1 + s2 + s3 + s4
    reasons.extend(r1 + r2 + r3 + r4)

    if regime == MarketRegime.SIDEWAYS:
        score *= params.sideways_score_multiplier
        if abs(score) < params.buy_threshold:
            logger.debug(
                "strategy_sideways_filtered",
                ticker=ticker,
                score=round(float(score), 2),
            )
            return None

    if score > 0 and not momentum_checker(df, params.momentum_confirmation_threshold):
        if abs(score) < params.buy_threshold + params.sideways_extra_threshold:
            logger.debug(
                "strategy_momentum_filtered",
                ticker=ticker,
                score=round(float(score), 2),
            )
            return None

    score = max(-100, min(100, score))
    if score == 0:
        return None
    return score, reasons


def passes_multi_timeframe_confluence(
    ticker: str,
    *,
    signal: Signal,
    trend_bias: TrendBias,
    multi_timeframe: bool,
    confluence_applier: ConfluenceApplier = apply_confluence,
) -> bool:
    """Apply trend/trigger confluence when multi-timeframe mode is active."""
    if not (multi_timeframe and getattr(settings, "MTF_ENABLED", True)):
        return True
    if confluence_applier(signal.signal_type, trend_bias, signal.reasons):
        return True
    logger.debug("strategy_mtf_filtered", ticker=ticker)
    return False
