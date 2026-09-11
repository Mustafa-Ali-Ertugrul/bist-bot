"""Decimal-based money helpers for TRY accounting (kuruş-exact).

Binary float cannot represent most decimal fractions (e.g. 0.1 + 0.2 != 0.3),
so repeated notional/fee/PnL accumulation drifts by kuruş dust. All helpers
take/return plain floats (public API unchanged) but compute via
``Decimal(str(value))`` and quantize HALF_UP:

- money amounts  -> 2 decimals (kuruş)
- BIST prices    -> 4 decimals (ara kademeler için)
- quantity dust  -> 1e-9 epsilon for == 0 checks
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

KURUS = Decimal("0.01")
PRICE_QUANT = Decimal("0.0001")

#: Residual below this is quantity dust, never a real open remainder.
QTY_EPS = 1e-9


def to_decimal(value: float | int | str | Decimal) -> Decimal:
    """Exact decimal from a float/int/str without binary-float dust."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: float | int | str | Decimal) -> float:
    """Round to kuruş (2 dp, HALF_UP) and return as float for API compat."""
    return float(to_decimal(value).quantize(KURUS, rounding=ROUND_HALF_UP))


def quantize_price(value: float | int | str | Decimal) -> float:
    """Round to 4 dp (HALF_UP) for BIST price levels."""
    return float(to_decimal(value).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP))


def calc_notional(quantity: float, price: float) -> float:
    """qty * price, kuruş-exact."""
    return float((to_decimal(quantity) * to_decimal(price)).quantize(KURUS, rounding=ROUND_HALF_UP))


def calc_cost(notional: float, rate: float) -> float:
    """notional * rate (commission/tax), kuruş-exact."""
    return float((to_decimal(notional) * to_decimal(rate)).quantize(KURUS, rounding=ROUND_HALF_UP))


def calc_pnl(exit_price: float, entry_price: float, quantity: float, fees: float = 0.0) -> float:
    """(exit - entry) * qty - fees, kuruş-exact."""
    pnl = (to_decimal(exit_price) - to_decimal(entry_price)) * to_decimal(quantity)
    pnl -= to_decimal(fees)
    return float(pnl.quantize(KURUS, rounding=ROUND_HALF_UP))


def is_zero_qty(remaining: float, eps: float = QTY_EPS) -> bool:
    """True when a quantity remainder is dust (never a real position)."""
    return abs(float(remaining)) < eps


__all__ = [
    "KURUS",
    "PRICE_QUANT",
    "QTY_EPS",
    "calc_cost",
    "calc_notional",
    "calc_pnl",
    "is_zero_qty",
    "quantize_money",
    "quantize_price",
    "to_decimal",
]
