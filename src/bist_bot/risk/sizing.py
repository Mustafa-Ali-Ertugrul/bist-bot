"""Position sizing and volatility helpers."""

from __future__ import annotations

from bist_bot.risk.models import RiskLevels


def calculate_atr_pct(levels: RiskLevels, price: float, atr_stop_mult: float) -> float:
    if price <= 0 or levels.stop_atr <= 0:
        return 0.0
    atr_distance = abs(price - levels.stop_atr) / max(atr_stop_mult, 1e-9)
    return atr_distance / price


def calculate_risk_throttle(atr_pct: float, atr_baseline_pct: float, atr_min_risk_scale: float) -> float:
    if atr_pct <= 0 or atr_pct <= atr_baseline_pct:
        return 1.0
    throttle = atr_baseline_pct / atr_pct
    return max(atr_min_risk_scale, min(1.0, throttle))


def apply_position_budget(price: float, levels: RiskLevels, capital: float, max_risk_pct: float) -> None:
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
    position_size = min(position_size, max_affordable)

    levels.position_size = max(0, position_size)
    levels.max_loss_tl = round(position_size * risk_per_share, 2)
    levels.risk_budget_tl = round(max_loss_tl, 2)


def calc_position_size(price: float, levels: RiskLevels, capital: float, max_risk_pct: float, atr_stop_mult: float, atr_baseline_pct: float, atr_min_risk_scale: float) -> RiskLevels:
    risk_per_share = price - levels.final_stop
    if risk_per_share <= 0:
        levels.position_size = 0
        levels.max_loss_tl = 0
        return levels

    levels.atr_pct = calculate_atr_pct(levels, price, atr_stop_mult)
    levels.volatility_scale = round(calculate_risk_throttle(levels.atr_pct, atr_baseline_pct, atr_min_risk_scale), 2)
    apply_position_budget(price, levels, capital, max_risk_pct)
    return levels
