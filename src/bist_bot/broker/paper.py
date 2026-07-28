"""Simulated paper broker for dry-run / paper trading."""

from __future__ import annotations

from bist_bot.broker.base import (
    Balance,
    Broker,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    coerce_order_type,
    coerce_side,
)
from bist_bot.execution.paper_broker import PaperBroker as _ExecutionPaperBroker
from bist_bot.risk.costs import TradingCosts


class PaperBroker(Broker):
    """In-memory paper broker that immediately fills market orders.

    Delegates fill/cash/position accounting to the battle-tested
    ``execution.paper_broker.PaperBroker`` implementation while exposing the
    product-facing ``submit_order`` / ``get_balance`` API.
    """

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        manual_confirm: bool = False,
        costs: TradingCosts | None = None,
    ) -> None:
        self._impl = _ExecutionPaperBroker(
            initial_cash=float(initial_cash),
            manual_confirm=bool(manual_confirm),
            costs=costs,
        )

    # --- product API ---

    def submit_order(
        self,
        ticker: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        return self._impl.place_order(
            ticker=ticker,
            side=coerce_side(side),
            quantity=float(quantity),
            order_type=coerce_order_type(order_type),
            price=price,
            stop_price=stop_price,
        )

    def cancel_order(self, order_id: str) -> bool:
        return self._impl.cancel_order(order_id)

    def get_positions(self) -> list[Position]:
        return self._impl.get_positions()

    def get_balance(self) -> Balance:
        return Balance.from_account_info(self._impl.get_account_info())

    def get_order_status(self, order_id: str) -> OrderStatus:
        return self._impl.get_order_status(order_id)

    # --- compatibility / helpers used by tests and execution layer ---

    def authenticate(self) -> bool:
        return self._impl.authenticate()

    def get_open_orders(self):
        return self._impl.get_open_orders()

    def fill_order(self, order_id: str, fill_price: float) -> bool:
        return self._impl.fill_order(order_id, fill_price)

    def confirm_order(self, order_id: str, fill_price: float | None = None) -> bool:
        return self._impl.confirm_order(order_id, fill_price=fill_price)

    @property
    def cash(self) -> float:
        return float(self._impl.cash)

    @property
    def positions(self) -> dict[str, Position]:
        return self._impl.positions

    @property
    def orders(self):
        return self._impl.orders

    @property
    def cumulative_fees(self) -> float:
        return float(self._impl.cumulative_fees)


__all__ = ["PaperBroker"]
