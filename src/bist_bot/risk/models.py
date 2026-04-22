"""Risk domain models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskLevels:
    stop_atr: float = 0.0
    stop_support: float = 0.0
    stop_fibonacci: float = 0.0
    stop_percent: float = 0.0
    stop_swing: float = 0.0

    target_atr: float = 0.0
    target_resistance: float = 0.0
    target_fibonacci: float = 0.0
    target_percent: float = 0.0
    target_swing: float = 0.0

    final_stop: float = 0.0
    final_target: float = 0.0
    risk_reward_ratio: float = 0.0
    risk_pct: float = 0.0
    reward_pct: float = 0.0
    position_size: int = 0
    max_loss_tl: float = 0.0
    risk_budget_tl: float = 0.0
    atr_pct: float = 0.0
    volatility_scale: float = 1.0
    correlation_scale: float = 1.0
    correlated_tickers: list[str] = field(default_factory=list)
    blocked_by_correlation: bool = False

    method_used: str = ""
    confidence: str = "confidence.low"
