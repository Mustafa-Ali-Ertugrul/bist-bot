"""BIST fiyat adımı (tick size) tablosu ve round_to_tick helper'ı.

Kaynaktan güncellenen BIST hisse senedi fiyat adımı kuralları (2023-2025+):
- p < 20.00 TL: 0.01 TL
- 20.00 <= p < 50.00 TL: 0.02 TL
- 50.00 <= p < 100.00 TL: 0.05 TL (50 TL üstü tick step 0.05'tir)
- 100.00 <= p < 250.00 TL: 0.10 TL (100 TL üstü tick step 0.10'dur)
- 250.00 <= p < 500.00 TL: 0.20 TL
- 500.00 <= p < 1000.00 TL: 0.50 TL
- p >= 1000.00 TL: 1.00 TL
"""

from __future__ import annotations

import math

# (upper_bound, tick_size) — upper_bound dahildir (exclusive).
_BIST_TICK_STEPS: list[tuple[float, float]] = [
    (20.00, 0.01),
    (50.00, 0.02),
    (100.00, 0.05),    # 50 TL <= p < 100 TL -> 0.05
    (250.00, 0.10),    # 100 TL <= p < 250 TL -> 0.10
    (500.00, 0.20),
    (1000.00, 0.50),
    (float("inf"), 1.00),
]


def get_tick_size(price: float) -> float:
    """Return the BIST minimum price step for a given price level."""
    for upper, tick in _BIST_TICK_STEPS:
        if price < upper:
            return tick
    return 1.00


def round_to_tick(price: float, side: str = "BUY") -> float:
    """Round a price to the nearest valid BIST tick.

    - side="BUY":  round UP (ceiling) — güvenli fiyat (daha pahalı alım)
    - side="SELL": round DOWN (floor) — güvenli fiyat (daha ucuza satım)

    Bu, canlı emir reddini önler.
    """
    if price <= 0:
        return 0.0
    tick = get_tick_size(price)
    if side.upper() == "BUY":
        return round(math.ceil(price / tick) * tick, 4)
    else:
        return round(math.floor(price / tick) * tick, 4)
