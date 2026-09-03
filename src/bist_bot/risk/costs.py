"""Central BIST trading cost model: commission, stamp tax, BSMV.

BIST cost structure (2024):
- Commission: negotiable, typically ~0.02% per side
- Stamp tax (Damga Vergisi): 0% buy, 0.093% sell
- BSMV (Banka ve Sigorta Muameleleri Vergisi): 0% buy, 0.05% sell
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradingCosts:
    commission_pct: float = 0.0002
    stamp_tax_pct: float = 0.00093
    bsmv_pct: float = 0.0005

    def buy_cost(self, notional: float) -> float:
        return notional * self.commission_pct

    def sell_cost(self, notional: float) -> float:
        return notional * (self.commission_pct + self.stamp_tax_pct + self.bsmv_pct)

    def round_trip_cost(self, buy_notional: float, sell_notional: float) -> float:
        return self.buy_cost(buy_notional) + self.sell_cost(sell_notional)


DEFAULT_COSTS = TradingCosts()


@dataclass(frozen=True)
class CostSchedule:
    """Canonical per-side trading cost schedule.

    All rates are per side and denominated as follows:
    - ``commission_bps``   : broker commission, basis points of notional
    - ``bsmv_pct``         : BSMV as fee-on-fee (percent of commission), both sides
    - ``exchange_fee_bps`` : exchange fee, basis points of notional
    - ``half_spread_bps``  : bid-ask HALF spread, basis points (price impact only)
    - ``slippage_bps``     : slippage, basis points (price impact only)
    - ``stamp_tax_bps``    : stamp tax, basis points of sell notional (0 for equities)
    - ``min_commission_tl``: floor for commission in TL (0 disables)

    Spread and slippage are price impact (inside the fill price), never cash fees.
    """

    commission_bps: float = 4.0
    bsmv_pct: float = 5.0
    exchange_fee_bps: float = 0.55
    half_spread_bps: float = 3.0
    slippage_bps: float = 2.0
    cost_version: str = "base_v1"
    stamp_tax_bps: float = 0.0
    min_commission_tl: float = 0.0


BASE_COSTS = CostSchedule(
    commission_bps=4.0,
    bsmv_pct=5.0,
    exchange_fee_bps=0.55,
    half_spread_bps=3.0,
    slippage_bps=2.0,
    cost_version="base_v1",
)

REALISTIC_DRAFT_COSTS = CostSchedule(
    commission_bps=8.0,
    bsmv_pct=5.0,
    exchange_fee_bps=0.55,
    half_spread_bps=5.0,
    slippage_bps=5.0,
    cost_version="realistic_draft_v1",
)

STRESS_COSTS = CostSchedule(
    commission_bps=16.0,
    bsmv_pct=5.0,
    exchange_fee_bps=1.10,
    half_spread_bps=10.0,
    slippage_bps=10.0,
    cost_version="stress_2x_v1",
)
