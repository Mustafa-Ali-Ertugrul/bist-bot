from __future__ import annotations

from datetime import datetime
from typing import Optional

from execution.base import BaseBroker, BrokerOrder, BrokerPosition, OrderSide, OrderStatus, OrderType


class PaperBroker(BaseBroker):
    """In-memory broker implementation for paper trading and lifecycle testing."""

    def __init__(self, initial_cash: float = 0.0) -> None:
        self.cash = float(initial_cash)
        self.positions: dict[str, BrokerPosition] = {}
        self.orders: dict[str, BrokerOrder] = {}

    def get_account_balance(self) -> float:
        return self.cash

    def get_positions(self) -> dict[str, BrokerPosition]:
        return dict(self.positions)

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> BrokerOrder:
        order = BrokerOrder(
            ticker=ticker,
            side=OrderSide(side.upper()),
            quantity=float(quantity),
            order_type=OrderType(order_type.upper()),
            price=price,
        )
        order.status = OrderStatus.SENT
        order.updated_at = datetime.utcnow()
        self.orders[order.order_id] = order

        if order.order_type is OrderType.MARKET:
            fill_price = price if price is not None else 0.0
            self._fill_order(order.order_id, quantity=order.quantity, fill_price=fill_price)
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return False
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.utcnow()
        return True

    def reject_order(self, order_id: str, reason: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return False
        order.status = OrderStatus.REJECTED
        order.metadata["reason"] = reason
        order.updated_at = datetime.utcnow()
        return True

    def partial_fill(self, order_id: str, quantity: float, fill_price: float) -> bool:
        return self._fill_order(order_id, quantity=quantity, fill_price=fill_price)

    def fill_order(self, order_id: str, fill_price: float) -> bool:
        order = self.orders.get(order_id)
        if order is None:
            return False
        return self._fill_order(order_id, quantity=order.remaining_quantity(), fill_price=fill_price)

    def _fill_order(self, order_id: str, quantity: float, fill_price: float) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FILLED}:
            return False

        fill_qty = min(float(quantity), order.remaining_quantity())
        if fill_qty <= 0:
            return False

        previous_filled = order.filled_quantity
        new_total = previous_filled + fill_qty
        if previous_filled <= 0:
            order.average_fill_price = fill_price
        elif order.average_fill_price is not None:
            order.average_fill_price = (
                (order.average_fill_price * previous_filled) + (fill_price * fill_qty)
            ) / new_total

        order.filled_quantity = new_total
        order.status = OrderStatus.FILLED if order.remaining_quantity() == 0 else OrderStatus.PARTIAL
        order.updated_at = datetime.utcnow()
        self._apply_fill(order, fill_qty, fill_price)
        return True

    def _apply_fill(self, order: BrokerOrder, quantity: float, fill_price: float) -> None:
        ticker = order.ticker
        if order.side is OrderSide.BUY:
            total_cost = quantity * fill_price
            self.cash -= total_cost
            position = self.positions.get(ticker)
            if position is None:
                self.positions[ticker] = BrokerPosition(
                    ticker=ticker,
                    quantity=quantity,
                    average_price=fill_price,
                )
                return

            combined_qty = position.quantity + quantity
            if combined_qty <= 0:
                self.positions.pop(ticker, None)
                return
            position.average_price = ((position.average_price * position.quantity) + total_cost) / combined_qty
            position.quantity = combined_qty
            position.updated_at = datetime.utcnow()
            return

        proceeds = quantity * fill_price
        self.cash += proceeds
        position = self.positions.get(ticker)
        if position is None:
            return
        position.quantity -= quantity
        position.updated_at = datetime.utcnow()
        if position.quantity <= 0:
            self.positions.pop(ticker, None)
