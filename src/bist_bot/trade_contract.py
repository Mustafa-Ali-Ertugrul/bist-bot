"""Canonical trade-economics contract.

Single source of truth describing how a long-only single-position round-trip
trade costs money. The backtest engine must match this contract, not the
reverse. Pure module: cost inputs come from ``CostSchedule`` in
``bist_bot.risk.costs``; no engine imports, no pandas, no side effects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from bist_bot.risk.costs import CostSchedule

Session = tuple[float, float, float, float]  # (open, high, low, close)


class ExitReason(str, Enum):
    """Canonical round-trip exit reasons."""

    STOP = "STOP"
    TARGET = "TARGET"
    STOP_GAP = "STOP_GAP"
    TARGET_GAP = "TARGET_GAP"
    SAME_BAR_STOP_FIRST = "SAME_BAR_STOP_FIRST"
    MAX_HOLD = "MAX_HOLD"
    DATA_END = "DATA_END"


@dataclass(frozen=True)
class TradeOutcome:
    """P&L and cost decomposition of a single round-trip trade (TL).

    All monetary fields are raw floats (no intermediate rounding). Fields are
    intentionally plain — the engine maps its trade fields onto this layout.
    """

    entry_date: str | None = None
    exit_date: str | None = None
    entry_ref_price: float = 0.0
    exit_ref_price: float = 0.0
    entry_fill: float = 0.0
    exit_fill: float = 0.0
    exit_reason: ExitReason = ExitReason.DATA_END
    shares: int = 0
    holding_sessions: int = 0
    notional_tl: float = 0.0
    gross_profit_tl: float = 0.0
    profit_tl: float = 0.0
    profit_pct: float = 0.0
    commission_tl: float = 0.0
    bsmv_tl: float = 0.0
    exchange_fee_tl: float = 0.0
    stamp_tax_tl: float = 0.0
    spread_impact_tl: float = 0.0
    slippage_impact_tl: float = 0.0
    total_cost_tl: float = 0.0


def calculate_trade_outcome(
    entry_price: float,
    stop_price: float | None,
    target_price: float | None,
    sessions: Sequence[Session],
    costs: CostSchedule,
    *,
    notional: float = 100_000.0,
    max_hold_sessions: int = 5,
    session_ids: Sequence[str] | None = None,
) -> TradeOutcome:
    """Simulate one long entry -> exit round trip under ``costs``.

    The entry is assumed filled at the open of ``sessions[0]``; the same
    session and each following one is then scanned for stop/target triggers,
    gap-first, then intrabar. Stop has priority when both hit in one bar.

    Raises ``ValueError`` on invalid inputs; otherwise pure arithmetic, no
    rounding.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")
    if len(sessions) == 0:
        raise ValueError("sessions must not be empty")
    if notional <= 0:
        raise ValueError("notional must be > 0")
    if max_hold_sessions < 1:
        raise ValueError("max_hold_sessions must be >= 1")
    if session_ids is not None and len(session_ids) != len(sessions):
        raise ValueError("session_ids must match sessions length")

    half_spread_rate = costs.half_spread_bps / 10_000
    slippage_rate = costs.slippage_bps / 10_000
    execution_rate = half_spread_rate + slippage_rate
    stop_active = stop_price is not None and stop_price > 0
    target_active = target_price is not None and target_price > 0

    entry_fill = entry_price * (1 + execution_rate)
    sizing_unit = entry_fill * (1 + (costs.commission_bps + costs.exchange_fee_bps) / 10_000)
    shares = int(notional / sizing_unit)
    if shares <= 0:
        raise ValueError("notional too small to size one share")

    entry_deployed = shares * entry_fill
    commission_e = max(entry_deployed * costs.commission_bps / 10_000, costs.min_commission_tl)
    bsmv_e = commission_e * costs.bsmv_pct / 100
    exchange_e = entry_deployed * costs.exchange_fee_bps / 10_000

    # Exit scan: gap checks first (including the entry session), then
    # intrabar stop/target, then max-hold / data-end fallback.
    exit_index: int | None = None
    exit_reason = ExitReason.DATA_END
    exit_ref = 0.0
    stop_level: float = stop_price if stop_price is not None else 0.0
    target_level: float = target_price if target_price is not None else 0.0
    scan_end = min(len(sessions), max_hold_sessions)
    for bar_index in range(scan_end):
        open_p, high_p, low_p, _ = sessions[bar_index]
        if stop_active and open_p <= stop_level:
            exit_reason = ExitReason.STOP_GAP
            exit_ref = open_p
        elif target_active and open_p >= target_level:
            exit_reason = ExitReason.TARGET_GAP
            exit_ref = open_p
        else:
            stop_hit = stop_active and low_p <= stop_level
            target_hit = target_active and high_p >= target_level
            if stop_hit and target_hit:
                exit_reason = ExitReason.SAME_BAR_STOP_FIRST
                exit_ref = stop_level
            elif stop_hit:
                exit_reason = ExitReason.STOP
                exit_ref = stop_level
            elif target_hit:
                exit_reason = ExitReason.TARGET
                exit_ref = target_level
            else:
                continue
        exit_index = bar_index
        break

    if exit_index is None:
        if len(sessions) >= max_hold_sessions:
            exit_index = max_hold_sessions - 1
            exit_reason = ExitReason.MAX_HOLD
        else:
            exit_index = len(sessions) - 1
            exit_reason = ExitReason.DATA_END
        exit_ref = sessions[exit_index][3]

    exit_fill = exit_ref * (1 - execution_rate)
    exit_notional = shares * exit_fill
    commission_x = max(exit_notional * costs.commission_bps / 10_000, costs.min_commission_tl)
    bsmv_x = commission_x * costs.bsmv_pct / 100
    exchange_x = exit_notional * costs.exchange_fee_bps / 10_000
    stamp_x = exit_notional * costs.stamp_tax_bps / 10_000

    commission_tl = commission_e + commission_x
    bsmv_tl = bsmv_e + bsmv_x
    exchange_fee_tl = exchange_e + exchange_x
    stamp_tax_tl = stamp_x
    spread_impact_tl = shares * (entry_price + exit_ref) * half_spread_rate
    slippage_impact_tl = shares * (entry_price + exit_ref) * slippage_rate
    gross_profit_tl = shares * (exit_ref - entry_price)
    profit_tl = shares * (exit_fill - entry_fill) - (
        commission_tl + bsmv_tl + exchange_fee_tl + stamp_tax_tl
    )
    total_cost_tl = (
        commission_tl
        + bsmv_tl
        + exchange_fee_tl
        + stamp_tax_tl
        + spread_impact_tl
        + slippage_impact_tl
    )
    profit_pct = (profit_tl / entry_deployed) * 100 if entry_deployed else 0.0

    return TradeOutcome(
        entry_date=session_ids[0] if session_ids is not None else None,
        exit_date=session_ids[exit_index] if session_ids is not None else None,
        entry_ref_price=entry_price,
        exit_ref_price=exit_ref,
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        exit_reason=exit_reason,
        shares=shares,
        holding_sessions=exit_index + 1,
        notional_tl=entry_deployed,
        gross_profit_tl=gross_profit_tl,
        profit_tl=profit_tl,
        profit_pct=profit_pct,
        commission_tl=commission_tl,
        bsmv_tl=bsmv_tl,
        exchange_fee_tl=exchange_fee_tl,
        stamp_tax_tl=stamp_tax_tl,
        spread_impact_tl=spread_impact_tl,
        slippage_impact_tl=slippage_impact_tl,
        total_cost_tl=total_cost_tl,
    )
