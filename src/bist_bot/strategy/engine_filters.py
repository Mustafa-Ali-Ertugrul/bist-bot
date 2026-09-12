"""Signal classification and filtering helpers for StrategyEngine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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
from bist_bot.strategy.scoring import combine_component_scores
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


@dataclass(frozen=True)
class ScoreBarContext:
    """Perf (#146 adım-4): skor-döngüsü için bar başına skaler bağlam.

    ``calculate_score_and_reasons``'in pencere DataFrame'inden (``df``)
    okuduğu TÜM değerleri taşır; verildiğinde bar başına ``df.iloc[...]``
    dilimi hiç kurulmaz:

    - ``n_bars``: trailing pencerenin satır sayısı (``len(sub)``)
    - ``mtf_sma_slope`` / ``mtf_ema_slope``: MTF çelişki kontrolünün
      okuduğu eğimler; ``None`` = sütun yok ya da yetersiz geçmiş
    - ``ema_slope``: ``score_trend``'in EMA eğimi (``_compute_ema_slope``
      karşılığı); ``nan`` = yetersiz geçmiş/sütun yok
    """

    n_bars: int
    mtf_sma_slope: float | None = None
    mtf_ema_slope: float | None = None
    ema_slope: float = float("nan")


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


def _mtf_contradiction_from_ctx(params: StrategyParams, ctx: ScoreBarContext) -> bool:
    """#146 adım-4: ``_has_mtf_slope_contradiction``in skaler karşılığı.

    ``ScoreBarContext.mtf_*_slope`` alanları, pencere dilimindeki eğimlerin
    (``df[col].iloc[-1] - df[col].iloc[-1 - slope_lookback]``) birebir
    değerleridir; ``None`` = sütun yok ya da yetersiz geçmiş (orijinal
    fonksiyonun ``return False`` dalları).
    """
    if not params.mtf_confluence_block_enabled:
        return False
    if ctx.mtf_sma_slope is None or ctx.mtf_ema_slope is None:
        return False
    sma_dir = component_direction(ctx.mtf_sma_slope)
    ema_dir = component_direction(ctx.mtf_ema_slope)
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
        bb_position == "ABOVE_UPPER"
        or cci >= params.chase_cci_threshold
        or distance_resistance <= params.chase_resist_pct
    )
    short_overextended = score < 0 and (
        bb_position == "BELOW_LOWER"
        or cci <= -params.chase_cci_threshold
        or distance_support <= params.chase_resist_pct
    )
    if not (long_overextended or short_overextended):
        return score
    adx = float(last.get("adx", 0.0) or 0.0)
    score_dir = component_direction(score)
    strong_trend_ride = (
        adx >= params.chase_strong_trend_adx
        and trend_dir == score_dir
        and momentum_dir == score_dir
    )
    cap = params.chase_strong_trend_cap if strong_trend_ride else params.chase_blocked_score_cap
    capped = min(score, cap) if score > 0 else max(score, -cap)
    if strong_trend_ride:
        reasons.append(f"Güçlü trend ride → skor {cap:g} ile sınırlandı")
    direction = "uzun" if score > 0 else "kısa"
    reasons.append(f"Aşırı uzama chase koruması → {direction} skor {cap:g} ile sınırlandı")
    return capped


def is_buy_signal(signal_type: SignalType) -> bool:
    """Return whether a signal opens or adds a long position."""
    return signal_type.is_buy


def is_sell_signal(signal_type: SignalType) -> bool:
    """Return whether a signal belongs to the short direction."""
    return signal_type.is_sell


def is_trade_actionable(signal: Signal, params: StrategyParams) -> bool:
    """Return True when `signal` crosses the directional trade thresholds.

    This is THE actionable contract shared by scanner, paper-trade, metrics,
    and notification layers. The decision is explicitly directional so the
    buy/sell asymmetry can never be confused:

    - buy side: ``params.buy_threshold <= score <= params.max_actionable_score``
    - sell side: ``score <= params.sell_threshold``
    - HOLD / RADAR / any other type: never actionable
    """
    if signal.signal_type.is_buy:
        return params.buy_actionable_score(signal.score)
    if signal.signal_type.is_sell:
        return params.sell_actionable_score(signal.score)
    return False


def classify_signal(
    params: StrategyParams,
    score: float,
    agreement_ratio: float | None = None,
) -> tuple[SignalType, str]:
    """Map a bounded numeric score to a signal type and confidence key."""
    if agreement_ratio is None:
        confidence = None
    elif agreement_ratio >= float(getattr(params, "agreement_full", 0.75)):
        confidence = "confidence.high"
    elif agreement_ratio >= float(getattr(params, "agreement_min", 0.5)):
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
    df: pd.DataFrame | None,
    *,
    last: pd.Series | Mapping[str, Any],
    prev: pd.Series | Mapping[str, Any],
    momentum_scorer: ScoreTwoRows,
    trend_scorer: TrendScorer,
    volume_scorer: ScoreTwoRows,
    structure_scorer: ScoreOneRow,
    momentum_checker: MomentumChecker = check_momentum_confirmation,
    reject_logger: RejectLogger | None = None,
    regime_sma: float | None = None,
    regime_last: pd.Series | Mapping[str, Any] | None = None,
    bar_ctx: ScoreBarContext | None = None,
) -> tuple[float, list[str], float | None] | None:
    """Calculate the bounded strategy score and explanatory reason list.

    ``last``/``prev`` satır protokolü: pd.Series VEYA Mapping (dict) —
    her ikisi ``.get``/``[]`` destekler (#146 adım-2: backtest skor
    döngüsü dict satır besleyerek bar başına pandas satır-Series kurulumu
    atlar; live motor Series beslemeye devam eder).

    ``regime_sma`` verildiğinde ``detect_regime``'in bar başına
    ``tail(lookback).mean()`` hesabı, ``regime_last`` verildiğinde
    ``df.iloc[-1]`` yeniden hesaplanmaz (backtest precompute'ı; değerler
    son satırın birebir karşılığı olmalıdır). None ise davranış değişmeden
    df'ten hesaplanır.

    ``bar_ctx`` (#146 adım-4) verildiğinde pencere DataFrame'inin (``df``)
    okuduğu TÜM değerler skaler olarak taşınır — ``df`` None olabilir ve
    bar başına pencere dilimi hiç kurulmaz (live motor df beslemeye devam
    eder, davranış aynıdır).
    """
    reasons: list[str] = []
    # Kwarg'lar YALNIZCA sağlandığında geçirilir: monkeypatch'lenmiş/custom
    # detect_regime implementasyonları (tek positional arg kabul eden)
    # bozulmaz; live yol çağrı imzası birebir eski hâlindedir.
    regime_kwargs: dict[str, object] = {}
    if regime_sma is not None:
        regime_kwargs["sma"] = regime_sma
    if regime_last is not None:
        regime_kwargs["last"] = regime_last
    if bar_ctx is not None:
        regime_kwargs["n_bars"] = bar_ctx.n_bars
    regime = detect_regime(df, **regime_kwargs)
    if bar_ctx is not None:
        mtf_contradiction = _mtf_contradiction_from_ctx(params, bar_ctx)
    else:
        mtf_contradiction = _has_mtf_slope_contradiction(params, df)
    if mtf_contradiction:
        regime = MarketRegime.SIDEWAYS
        reasons.append("MTF çelişki: SMA20 ve EMA200 eğimleri zıt")
    if regime == MarketRegime.SIDEWAYS:
        reasons.append("Piyasa rejimi yatay - skor etkisi azaltildi")

    s1, r1 = momentum_scorer(last, prev)
    s2, r2 = trend_scorer(last, prev, df)
    s3, r3 = volume_scorer(last, prev)
    s4, r4 = structure_scorer(last)
    reasons.extend(r1 + r2 + r3 + r4)

    raw_score, _raw_components = combine_component_scores(params, s1, s2, s3, s4)
    if getattr(params, "normalized_component_scoring", False):
        reasons.append("Araştırma profili: bileşen skorları normalize edildi")
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

    score, _post_components = combine_component_scores(params, s1, s2, s3, s4)
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
    agreement_divisor = float(getattr(params, "agreement_divisor", 4.0)) or 4.0
    agreement_ratio = agree / agreement_divisor

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

    if score != 0:
        # Perf (#146 adım-3/4): default momentum checker'da precompute'ları
        # yeniden kullan; custom checker'lar (testler) 2-arg imzasıyla
        # çağrılmaya devam eder — identity guard sayesinde TypeError yok.
        if momentum_checker is check_momentum_confirmation:
            momentum_ok = momentum_checker(
                df,
                params.momentum_confirmation_threshold,
                last=regime_last,
                sma=regime_sma,
                n_bars=bar_ctx.n_bars if bar_ctx is not None else None,
            )
        else:
            momentum_ok = momentum_checker(df, params.momentum_confirmation_threshold)
        if not momentum_ok:
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

    # Deney F — pv confirmation gate (opt-in, default off = mevcut davranış).
    # Son giriş filtresi: long aday (skor buy_threshold üstünde) fakat
    # fiyat-hacim boğa teyidi yoksa reddet. P0/P1 kanıtı: pv_bull=0 alt
    # kümesi mean -%1.51 (n=153), pv_bull=1 mean +%1.03 (n=355).
    if params.pv_confirmation_required and score >= params.buy_threshold:
        pv_direction = last.get("price_volume_direction", "NONE")
        if pv_direction != "BULLISH_CONFIRMATION":
            logger.debug(
                "strategy_pv_confirmation_filtered",
                ticker=ticker,
                score=round(float(score), 2),
                pv_direction=pv_direction,
            )
            if reject_logger is not None:
                reject_logger(
                    stage="scoring",
                    reason_code="score_filtered_pv_confirmation",
                    score=round(float(score), 2),
                    reason_detail=(
                        "long candidate without bullish price-volume confirmation "
                        f"(pv_direction={pv_direction})"
                    ),
                )
            return None

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
