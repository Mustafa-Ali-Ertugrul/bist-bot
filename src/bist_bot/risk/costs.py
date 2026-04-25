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
