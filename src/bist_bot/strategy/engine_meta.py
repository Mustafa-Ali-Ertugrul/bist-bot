"""Risk and meta-model integration helpers for StrategyEngine."""

from __future__ import annotations

from typing import Any

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.ml.features import build_feature_payload
from bist_bot.risk import RiskLevels, RiskManager
from bist_bot.strategy.engine_filters import is_buy_signal
from bist_bot.strategy.regime import TrendBias
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="strategy")


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
        trend_bias=float(trend_bias == TrendBias.LONG)
        - float(trend_bias == TrendBias.SHORT),
    )


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
) -> RiskLevels | None:
    """Apply sector, portfolio, liquidity, and meta-model guards."""
    if not is_buy_signal(signal_type):
        return risk_levels
    if enforce_sector_limit and not risk_manager.check_sector_limit(ticker):
        logger.debug("strategy_sector_filtered", ticker=ticker)
        return None

    price = float(last["close"])
    risk_levels = risk_manager.apply_portfolio_risk(ticker, df, risk_levels)
    if risk_levels.blocked_by_correlation or risk_levels.position_size <= 0:
        logger.debug("strategy_portfolio_risk_filtered", ticker=ticker)
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
            return None
    return risk_levels


def append_signal_reasons(signal: Signal, risk_levels: RiskLevels) -> None:
    """Append risk sizing and meta-model details to a generated signal."""
    signal.reasons.append(
        f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}"
    )
    signal.reasons.append(
        f"Pozisyon: {risk_levels.position_size} lot | Risk Butcesi: TL{risk_levels.risk_budget_tl:.2f}"
    )
    signal.reasons.append(
        f"Volatilite throttle: x{risk_levels.volatility_scale:.2f} | ATR%: %{risk_levels.atr_pct * 100:.2f}"
    )
    if risk_levels.signal_probability is not None:
        signal.reasons.append(
            f"Meta-model: P(up) %{risk_levels.signal_probability * 100:.1f} | Kelly %{risk_levels.kelly_fraction * 100:.2f}"
        )
    if risk_levels.liquidity_value > 0:
        signal.reasons.append(
            f"Likidite: TL{risk_levels.liquidity_value:,.0f} ort. islem degeri"
        )
    if risk_levels.correlated_tickers:
        signal.reasons.append(
            f"Korelasyon limiti: x{risk_levels.correlation_scale:.2f} | Iliskili: {', '.join(risk_levels.correlated_tickers)}"
        )
