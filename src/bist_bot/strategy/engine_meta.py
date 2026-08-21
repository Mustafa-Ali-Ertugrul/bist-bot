"""Risk and meta-model integration helpers for StrategyEngine."""

from __future__ import annotations

from typing import Any

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.ml.features import build_feature_payload
from bist_bot.risk import RiskLevels, RiskManager
from bist_bot.strategy.engine_filters import is_buy_signal, is_sell_signal
from bist_bot.strategy.regime import TrendBias
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="strategy")
RejectLogger = Any


def build_meta_features(
    last: pd.Series,
    *,
    score: float,
    trend_bias: TrendBias,
    risk_levels: RiskLevels,
) -> dict[str, float]:
    """Build the flat feature payload expected by the probability model."""
    return build_feature_payload(
        last,
        score=score,
        stop_loss=float(risk_levels.final_stop),
        target_price=float(risk_levels.final_target),
        volatility_scale=float(risk_levels.volatility_scale),
        correlation_scale=float(risk_levels.correlation_scale),
        trend_bias=float(trend_bias == TrendBias.LONG) - float(trend_bias == TrendBias.SHORT),
    )


def _apply_short_rr(levels: RiskLevels, price: float) -> None:
    """Fill short-side R/R and percentage fields from the final geometry.

    Valid short geometry requires ``final_stop > price > final_target``.
    Degenerate or inverted levels zero all three fields so no fake reward
    ratio is advertised downstream.
    """
    risk = levels.final_stop - price
    reward = price - levels.final_target
    valid = risk > 0 and reward > 0
    levels.risk_pct = round(-risk / price * 100, 2) if valid else 0.0
    levels.reward_pct = round(reward / price * 100, 2) if valid else 0.0
    levels.risk_reward_ratio = round(reward / risk, 2) if valid else 0.0


def _build_non_buy_levels(
    df: pd.DataFrame,
    last: pd.Series,
    *,
    atr_stop_mult: float = 2.0,
    atr_target_mult: float = 3.0,
) -> RiskLevels:
    """Build a short-side trade plan (stop/target/R-R) for non-buy signals.

    HOLD and RADAR signals also receive this descriptive short plan so their
    persisted stop/target never reuse a long geometry, but only sell-type
    signals advertise the plan in user-facing reasons (see
    ``append_signal_reasons``). Short position sizing is intentionally not
    applied here; it lands in Faz 2 after signal-replay backtest evidence.
    """
    price = float(last["close"])
    atr_series = df.get("atr")
    atr_val: float | None = None
    if atr_series is not None and len(atr_series) > 0:
        raw_atr = atr_series.iloc[-1]
        try:
            atr_val = float(raw_atr) if pd.notna(raw_atr) else None
        except (TypeError, ValueError):
            atr_val = None
    if atr_val is not None and atr_val > 0:
        final_stop = round(price + (atr_stop_mult * atr_val), 2)
        final_target = round(price - (atr_target_mult * atr_val), 2)
        method_used = (
            f"Short trade plan: ATR-based (stop=+{atr_stop_mult:.1f}*ATR, "
            f"target=-{atr_target_mult:.1f}*ATR)"
        )
    else:
        final_stop = round(price * 1.05, 2)
        final_target = round(price * 0.92, 2)
        method_used = "Short trade plan: fixed 5% stop / 8% target (ATR missing)"
    levels = RiskLevels(
        final_stop=final_stop,
        final_target=final_target,
        position_size=0,
        method_used=method_used,
    )
    _apply_short_rr(levels, price)
    return levels


def apply_buy_side_risk(
    risk_manager: RiskManager,
    meta_model: Any | None,
    ticker: str,
    df: pd.DataFrame,
    *,
    signal_type: SignalType,
    enforce_sector_limit: bool,
    last: pd.Series,
    score: float,
    trend_bias: TrendBias,
    risk_levels: RiskLevels,
    reject_logger: RejectLogger | None = None,
) -> RiskLevels | None:
    """Apply sector, portfolio, liquidity, and meta-model guards.

    Non-buy signals (SELL/WEAK_SELL/STRONG_SELL and HOLD/RADAR) bypass all
    buy-side risk guards and instead receive a short-side trade plan built by
    :func:`_build_non_buy_levels`: short stop above price, short target below
    it, and a matching R/R. This keeps the signal's persisted stop_loss and
    target_price consistent with a short geometry instead of silently reusing
    long levels. HOLD/RADAR also get the plan data, but only sell-type
    signals surface it in user-facing reasons via ``append_signal_reasons``.
    The name is kept for history; consider renaming once the short-sizing
    work lands in Faz 2.
    """
    if not is_buy_signal(signal_type):
        return _build_non_buy_levels(
            df,
            last,
            atr_stop_mult=float(getattr(risk_manager, "atr_stop_mult", 2.0)),
            atr_target_mult=float(getattr(risk_manager, "atr_target_mult", 3.0)),
        )
    if enforce_sector_limit and not risk_manager.check_sector_limit(ticker):
        logger.debug("strategy_sector_filtered", ticker=ticker)
        if reject_logger is not None:
            reject_logger(
                stage="risk",
                reason_code="sector_limit_blocked",
                score=round(float(score), 2),
                signal_type=signal_type.name,
                reason_detail="sector exposure limit reached",
            )
        return None

    price = float(last["close"])
    risk_levels = risk_manager.apply_portfolio_risk(ticker, df, risk_levels)
    if risk_levels.blocked_by_correlation or risk_levels.position_size <= 0:
        logger.debug("strategy_portfolio_risk_filtered", ticker=ticker)
        if reject_logger is not None:
            reject_logger(
                stage="risk",
                reason_code="portfolio_risk_blocked",
                score=round(float(score), 2),
                signal_type=signal_type.name,
                position_size=risk_levels.position_size,
                blocked_by_correlation=risk_levels.blocked_by_correlation,
                liquidity_value=round(float(risk_levels.liquidity_value), 2),
                reason_detail="portfolio correlation or sizing constraints blocked candidate",
            )
        return None

    if meta_model is not None and hasattr(meta_model, "predict_probability"):
        signal_probability = float(
            meta_model.predict_probability(
                build_meta_features(
                    last,
                    score=score,
                    trend_bias=trend_bias,
                    risk_levels=risk_levels,
                )
            )
        )
        risk_levels = risk_manager.apply_signal_probability(
            df,
            price,
            risk_levels,
            signal_probability,
        )
        if risk_levels.position_size <= 0:
            logger.debug("strategy_meta_model_filtered", ticker=ticker)
            if reject_logger is not None:
                reject_logger(
                    stage="risk",
                    reason_code="meta_model_blocked",
                    score=round(float(score), 2),
                    signal_type=signal_type.name,
                    position_size=risk_levels.position_size,
                    signal_probability=risk_levels.signal_probability,
                    liquidity_value=round(float(risk_levels.liquidity_value), 2),
                    reason_detail="meta-model probability sizing reduced position to zero",
                )
            return None
    return risk_levels


def append_signal_reasons(signal: Signal, risk_levels: RiskLevels) -> None:
    """Append risk sizing and meta-model details to a generated signal."""
    if is_sell_signal(signal.signal_type):
        if risk_levels.risk_reward_ratio > 0:
            signal.reasons.append(
                f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}"
            )
        else:
            signal.reasons.append("Short trade plan unavailable | invalid geometry")
        return
    if not is_buy_signal(signal.signal_type):
        signal.reasons.append("Long trade plan not generated: signal is not buy-side")
        return
    signal.reasons.append(f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}")
    signal.reasons.append(
        f"Pozisyon: {risk_levels.position_size} lot | Risk Bütçesi: TL{risk_levels.risk_budget_tl:.2f}"
    )
    signal.reasons.append(
        f"Volatilite throttle: x{risk_levels.volatility_scale:.2f} | ATR%: %{risk_levels.atr_pct * 100:.2f}"
    )
    if risk_levels.signal_probability is not None:
        signal.reasons.append(
            f"Meta-model: P(up) %{risk_levels.signal_probability * 100:.1f} | Kelly %{risk_levels.kelly_fraction * 100:.2f}"
        )
    if risk_levels.liquidity_value > 0:
        signal.reasons.append(f"Likidite: TL{risk_levels.liquidity_value:,.0f} ort. islem degeri")
    if risk_levels.correlated_tickers:
        signal.reasons.append(
            f"Korelasyon limiti: x{risk_levels.correlation_scale:.2f} | Iliskili: {', '.join(risk_levels.correlated_tickers)}"
        )
