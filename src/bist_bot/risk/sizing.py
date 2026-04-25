"""Position sizing and volatility helpers."""

from __future__ import annotations

import logging

from bist_bot.risk.models import RiskLevels

logger = logging.getLogger(__name__)


def calculate_atr_pct(levels: RiskLevels, price: float, atr_stop_mult: float) -> float:
    if price <= 0 or levels.stop_atr <= 0:
        return 0.0
    atr_distance = abs(price - levels.stop_atr) / max(atr_stop_mult, 1e-9)
    return atr_distance / price


def calculate_risk_throttle(
    atr_pct: float, atr_baseline_pct: float, atr_min_risk_scale: float
) -> float:
    if atr_pct <= 0 or atr_pct <= atr_baseline_pct:
        return 1.0
    throttle = atr_baseline_pct / atr_pct
    return max(atr_min_risk_scale, min(1.0, throttle))


def apply_position_budget(
    price: float,
    levels: RiskLevels,
    capital: float,
    max_risk_pct: float,
    max_position_cap_pct: float = 90.0,
) -> None:
    risk_per_share = price - levels.final_stop
    if risk_per_share <= 0:
        levels.position_size = 0
        levels.max_loss_tl = 0
        levels.risk_budget_tl = 0
        return

    budget_scale = levels.volatility_scale * levels.correlation_scale
    max_loss_tl = capital * (max_risk_pct / 100) * budget_scale
    position_size = int(max_loss_tl / risk_per_share) if risk_per_share > 0 else 0
    max_affordable = int(capital * 0.9 / price)
    max_position_cap = int(capital * (max_position_cap_pct / 100.0) / price) if price > 0 else 0
    position_size = min(position_size, max_affordable, max_position_cap)

    levels.position_size = max(0, position_size)
    levels.max_loss_tl = round(position_size * risk_per_share, 2)
    levels.risk_budget_tl = round(max_loss_tl, 2)

    if levels.position_size == 0 and capital > 0:
        logger.warning(
            "position_size_zero capital=%.0f price=%.2f risk_per_share=%.2f "
            "max_affordable=%d max_position_cap=%d -- INITIAL_CAPITAL veya "
            "MAX_POSITION_CAP_PCT yetersiz olabilir",
            capital,
            price,
            risk_per_share,
            max_affordable,
            max_position_cap,
        )


def calculate_kelly_fraction(win_probability: float, reward_to_risk_ratio: float) -> float:
    if reward_to_risk_ratio <= 0:
        return 0.0
    probability = max(0.0, min(1.0, win_probability))
    loss_probability = 1.0 - probability
    return max(0.0, probability - (loss_probability / reward_to_risk_ratio))


def estimate_liquidity_value(levels: RiskLevels, liquidity_value: float | None) -> None:
    levels.liquidity_value = round(max(0.0, float(liquidity_value or 0.0)), 2)


def apply_probability_sizing(
    price: float,
    levels: RiskLevels,
    capital: float,
    *,
    signal_probability: float,
    kelly_fraction_scale: float,
    max_position_cap_pct: float,
    min_signal_probability: float,
    liquidity_value: float | None,
    min_liquidity_value: float,
    daily_loss_limit_reached: bool,
) -> RiskLevels:
    levels.signal_probability = round(max(0.0, min(1.0, signal_probability)), 4)
    estimate_liquidity_value(levels, liquidity_value)

    if daily_loss_limit_reached:
        levels.position_size = 0
        levels.max_loss_tl = 0.0
        levels.blocked_by_daily_loss = True
        return levels

    if levels.liquidity_value and levels.liquidity_value < min_liquidity_value:
        levels.position_size = 0
        levels.max_loss_tl = 0.0
        levels.blocked_by_liquidity = True
        return levels

    if levels.signal_probability < min_signal_probability:
        levels.position_size = 0
        levels.max_loss_tl = 0.0
        levels.blocked_by_probability = True
        return levels

    risk_per_share = price - levels.final_stop
    reward_per_share = levels.final_target - price
    if risk_per_share <= 0 or reward_per_share <= 0 or levels.position_size <= 0:
        levels.position_size = 0
        levels.max_loss_tl = 0.0
        return levels

    reward_to_risk_ratio = reward_per_share / risk_per_share
    levels.full_kelly_fraction = round(
        calculate_kelly_fraction(levels.signal_probability, reward_to_risk_ratio), 4
    )
    levels.kelly_fraction = round(
        min(
            max_position_cap_pct / 100.0,
            levels.full_kelly_fraction * max(kelly_fraction_scale, 0.0),
        ),
        4,
    )
    if levels.kelly_fraction <= 0:
        levels.position_size = 0
        levels.max_loss_tl = 0.0
        levels.blocked_by_probability = True
        return levels

    max_position_value = capital * (max_position_cap_pct / 100.0)
    kelly_position_value = capital * levels.kelly_fraction
    capped_value = min(max_position_value, kelly_position_value)
    kelly_position_size = int(capped_value / price) if price > 0 else 0
    levels.position_size = min(levels.position_size, max(0, kelly_position_size))
    levels.max_loss_tl = round(levels.position_size * risk_per_share, 2)
    return levels


def calc_position_size(
    price: float,
    levels: RiskLevels,
    capital: float,
    max_risk_pct: float,
    atr_stop_mult: float,
    atr_baseline_pct: float,
    atr_min_risk_scale: float,
    max_position_cap_pct: float = 90.0,
) -> RiskLevels:
    risk_per_share = price - levels.final_stop
    if risk_per_share <= 0:
        levels.position_size = 0
        levels.max_loss_tl = 0
        return levels

    levels.atr_pct = calculate_atr_pct(levels, price, atr_stop_mult)
    levels.volatility_scale = round(
        calculate_risk_throttle(levels.atr_pct, atr_baseline_pct, atr_min_risk_scale), 2
    )
    apply_position_budget(price, levels, capital, max_risk_pct, max_position_cap_pct)
    return levels
