"""In-memory paper broker for testing and dry execution flows."""

from __future__ import annotations

from bist_bot.execution.base import (
    AccountInfo,
    BaseExecutionProvider,
    Order,
    OrderResult,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
    Position,
    utc_now,
)
from bist_bot.risk.costs import DEFAULT_COSTS, TradingCosts


class PaperBroker(BaseExecutionProvider):
    """Simple in-memory broker implementation."""

    def __init__(
        self,
        initial_cash: float = 0.0,
        manual_confirm: bool = False,
        costs: TradingCosts | None = None,
    ) -> None:
        self.cash = float(initial_cash)
        self.manual_confirm = manual_confirm
        self.costs = costs or DEFAULT_COSTS
        self.cumulative_fees: float = 0.0
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}

    def authenticate(self) -> bool:
        return True

    def get_positions(self) -> list[Position]:
        return list(self.positions.values())

    def get_account_info(self) -> AccountInfo:
        market_value = sum(position.quantity * position.average_price for position in self.positions.values())
        equity = self.cash + market_value
        return AccountInfo(cash_balance=self.cash, buying_power=self.cash, equity=equity)

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        state = OrderState.CREATED if self.manual_confirm else OrderState.SENT
        order = Order(
            ticker=ticker,
            side=side,
            quantity=float(quantity),
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            state=state,
        )
        order.updated_at = utc_now()
        self.orders[order.order_id] = order

        if not self.manual_confirm and order.order_type is OrderType.MARKET:
            fill_price = price if price is not None else 0.0
            self._fill_order(order.order_id, quantity=order.quantity, fill_price=fill_price)

        return OrderResult(
            accepted=True,
            order_id=order.order_id,
            broker_order_id=order.order_id,
            state=order.state,
        )

    def confirm_order(self, order_id: str, fill_price: float | None = None) -> bool:
        """Manually approve and execute a CREATED order."""
        order = self.orders.get(order_id)
        if order is None or order.state != OrderState.CREATED:
            return False
            
        order.state = OrderState.SENT
        order.updated_at = utc_now()
        if order.order_type is OrderType.MARKET or fill_price is not None:
            exec_price = fill_price if fill_price is not None else (order.price or 0.0)
            return self._fill_order(order_id, order.remaining_quantity(), exec_price)
        return True

    def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}:
            return False
        order.state = OrderState.CANCELLED
        order.updated_at = utc_now()
        return True

    def get_order_status(self, order_id: str) -> OrderStatus:
        order = self.orders[order_id]
        return OrderStatus(
            order_id=order.order_id,
            broker_order_id=order.broker_order_id or order.order_id,
            state=order.state,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
        )

    def get_open_orders(self) -> list[Order]:
        return [order for order in self.orders.values() if order.state in {OrderState.SENT, OrderState.PARTIAL}]

    def reject_order(self, order_id: str, reason: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}:
            return False
        order.state = OrderState.REJECTED
        order.metadata["reason"] = reason
        order.updated_at = utc_now()
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
        if order is None or order.state in {OrderState.CANCELLED, OrderState.REJECTED, OrderState.FILLED}:
            return False

        fill_qty = min(float(quantity), order.remaining_quantity())
        if fill_qty <= 0:
            return False

        previous_filled = order.filled_quantity
        new_total = previous_filled + fill_qty
        if previous_filled <= 0:
            order.average_fill_price = fill_price
        elif order.average_fill_price is not None:
            order.average_fill_price = ((order.average_fill_price * previous_filled) + (fill_price * fill_qty)) / new_total

        order.filled_quantity = new_total
        order.state = OrderState.FILLED if order.remaining_quantity() == 0 else OrderState.PARTIAL
        order.updated_at = utc_now()
        self._apply_fill(order, fill_qty, fill_price)
        return True

    def _apply_fill(self, order: Order, quantity: float, fill_price: float) -> None:
        ticker = order.ticker
        notional = quantity * fill_price
        if order.side is OrderSide.BUY:
            fee = self.costs.buy_cost(notional)
            self.cash -= notional + fee
            self.cumulative_fees += fee
            position = self.positions.get(ticker)
            if position is None:
                self.positions[ticker] = Position(ticker=ticker, quantity=quantity, average_price=fill_price, market_value=notional)
                return

            combined_qty = position.quantity + quantity
            if combined_qty <= 0:
                self.positions.pop(ticker, None)
                return
            position.average_price = ((position.average_price * position.quantity) + notional) / combined_qty
            position.quantity = combined_qty
            position.market_value = combined_qty * position.average_price
            position.updated_at = utc_now()
            return

        fee = self.costs.sell_cost(notional)
        self.cash += notional - fee
        self.cumulative_fees += fee
        position = self.positions.get(ticker)
        if position is None:
            return
        position.quantity -= quantity
        position.market_value = max(position.quantity, 0.0) * position.average_price
        position.updated_at = utc_now()
        if position.quantity <= 0:
            self.positions.pop(ticker, None)
