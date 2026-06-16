"""Portfolio-level risk limits and guardrails.

Enforced independently from per-trade RiskManager / TradingCosts.
Acts as a gate before AlpacaBroker.place_order().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class PortfolioLimits:
    MAX_OPEN_POSITIONS: int = 5
    MAX_POSITION_SIZE: float = 0.20
    MAX_DAILY_LOSS: float = 0.03
    MAX_ACCOUNT_DRAWDOWN: float = 0.15


@dataclass
class PortfolioState:
    equity: float = 0.0
    cash: float = 0.0
    peak_equity: float = 0.0
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    today_trades: list[dict[str, Any]] = field(default_factory=list)
    _today: datetime = field(default_factory=lambda: datetime.now(UTC).date())

    def daily_pnl(self) -> float:
        return sum(t.get("pnl", 0.0) for t in self.today_trades)

    def current_drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    def refresh_date(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._today:
            self._today = today
            self.today_trades.clear()


@dataclass
class LimitCheckResult:
    allowed: bool
    reason: str = ""
    blocked_by: str = ""


def check_order_against_limits(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    state: PortfolioState,
    limits: PortfolioLimits | None = None,
) -> LimitCheckResult:
    if limits is None:
        limits = PortfolioLimits()

    state.refresh_date()
    notional = quantity * price

    # 1. Max open positions
    open_count = len(state.open_positions)
    position_exists = any(p.get("symbol") == symbol for p in state.open_positions)
    if not position_exists and open_count >= limits.MAX_OPEN_POSITIONS:
        return LimitCheckResult(
            allowed=False,
            reason=f"Max open positions ({limits.MAX_OPEN_POSITIONS}) reached.",
            blocked_by="MAX_OPEN_POSITIONS",
        )

    # 2. Max position size
    position_value = sum(
        p.get("market_value", 0.0) for p in state.open_positions if p.get("symbol") == symbol
    )
    if side == "BUY" and state.equity > 0:
        new_position_pct = (position_value + notional) / state.equity
        if new_position_pct > limits.MAX_POSITION_SIZE:
            return LimitCheckResult(
                allowed=False,
                reason=f"Position size {new_position_pct:.2%} > limit {limits.MAX_POSITION_SIZE:.2%}.",
                blocked_by="MAX_POSITION_SIZE",
            )

    # 3. Max daily loss
    if state.equity > 0:
        daily_pnl = state.daily_pnl()
        projected_loss = 0.0
        if side == "SELL":
            avg_cost = next(
                (p["average_price"] for p in state.open_positions if p["symbol"] == symbol), price
            )
            projected_loss = quantity * (avg_cost - price)
        projected_daily_pnl = daily_pnl + projected_loss
        if projected_daily_pnl < 0 and abs(projected_daily_pnl) / state.equity > limits.MAX_DAILY_LOSS:
            return LimitCheckResult(
                allowed=False,
                reason=f"Projected daily loss {abs(projected_daily_pnl)/state.equity:.2%} > limit {limits.MAX_DAILY_LOSS:.2%}.",
                blocked_by="MAX_DAILY_LOSS",
            )

    # 4. Max drawdown
    drawdown = state.current_drawdown()
    if drawdown >= limits.MAX_ACCOUNT_DRAWDOWN:
        return LimitCheckResult(
            allowed=False,
            reason=f"Account drawdown {drawdown:.2%} >= limit {limits.MAX_ACCOUNT_DRAWDOWN:.2%}.",
            blocked_by="MAX_ACCOUNT_DRAWDOWN",
        )

    return LimitCheckResult(allowed=True, reason="All portfolio limits passed.")
