"""Broker abstraction contracts for order routing and account state.

This package is a thin, user-facing facade over ``bist_bot.execution``.
Existing AlgoLab provider remains under ``execution/``; paper/live
entry points preferred by application code live here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from bist_bot.execution.base import (
    AccountInfo,
    Order,
    OrderResult,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
    Position,
)


@dataclass
class Balance:
    """Account cash / equity snapshot returned by ``Broker.get_balance``."""

    cash: float
    buying_power: float
    equity: float
    currency: str = "TRY"
    account_id: str | None = None

    @classmethod
    def from_account_info(cls, info: AccountInfo) -> Balance:
        return cls(
            cash=float(info.cash_balance),
            buying_power=float(info.buying_power),
            equity=float(info.equity),
            currency=str(info.currency or "TRY"),
            account_id=info.account_id,
        )


def coerce_side(side: OrderSide | str) -> OrderSide:
    if isinstance(side, OrderSide):
        return side
    return OrderSide(str(side).upper())


def coerce_order_type(order_type: OrderType | str) -> OrderType:
    if isinstance(order_type, OrderType):
        return order_type
    return OrderType(str(order_type).upper())


class Broker(ABC):
    """Application-facing broker contract.

    Method names match the product API (``submit_order`` / ``get_balance``)
    while remaining compatible with the lower-level ``ExecutionProvider``
    surface used by ``ExecutionService`` and live adapters.
    """

    @abstractmethod
    def submit_order(
        self,
        ticker: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        """Submit an order and return the broker acknowledgement."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True when cancellation is accepted."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return current open positions."""

    @abstractmethod
    def get_balance(self) -> Balance:
        """Return cash / equity balances."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Return latest known status for ``order_id``."""

    # --- Optional compatibility hooks used by ExecutionService / trackers ---

    def authenticate(self) -> bool:
        return True

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        """Alias for ``submit_order`` so ExecutionService can call place_order."""
        return self.submit_order(
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
        )

    def get_account_info(self) -> AccountInfo:
        bal = self.get_balance()
        return AccountInfo(
            cash_balance=bal.cash,
            buying_power=bal.buying_power,
            equity=bal.equity,
            currency=bal.currency,
            account_id=bal.account_id,
        )

    def get_open_orders(self) -> list[Order]:
        return []


__all__ = [
    "AccountInfo",
    "Balance",
    "Broker",
    "Order",
    "OrderResult",
    "OrderSide",
    "OrderState",
    "OrderStatus",
    "OrderType",
    "Position",
    "coerce_order_type",
    "coerce_side",
]
