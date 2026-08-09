"""Alpaca execution provider using alpaca-py SDK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus
from alpaca.trading.enums import OrderType as AlpacaOrderType
from alpaca.trading.enums import QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

from bist_bot.app_logging import get_logger
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

logger = get_logger(__name__, component="alpaca_broker")


@dataclass(frozen=True)
class AlpacaCredentials:
    api_key: str
    secret_key: str


class AlpacaBroker(BaseExecutionProvider):
    """Alpaca paper/live execution provider with optional dry-run safety."""

    def __init__(
        self,
        credentials: AlpacaCredentials,
        *,
        paper: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.credentials = credentials
        self.paper = paper
        self.dry_run = dry_run
        self._client = TradingClient(
            credentials.api_key,
            credentials.secret_key,
            paper=paper,
        )

    def authenticate(self) -> bool:
        try:
            self._client.get_account()
            return True
        except APIError as exc:
            logger.error("alpaca_auth_failed", code=exc.status_code, message=str(exc))
            return False
        except Exception as exc:
            logger.error("alpaca_auth_error", error_type=type(exc).__name__, message=str(exc))
            return False

    def get_positions(self) -> list[Position]:
        raw_positions = self._client.get_all_positions()
        return [
            Position(
                ticker=str(p.symbol),
                quantity=float(p.qty),
                average_price=float(p.avg_entry_price) if p.avg_entry_price else 0.0,
                market_value=float(p.market_value) if p.market_value else 0.0,
                unrealized_pnl=float(p.unrealized_pl) if p.unrealized_pl else 0.0,
                updated_at=utc_now(),
            )
            for p in raw_positions
        ]

    def get_account_info(self) -> AccountInfo:
        account = self._client.get_account()
        return AccountInfo(
            cash_balance=float(account.cash) if account.cash else 0.0,
            buying_power=float(account.buying_power) if account.buying_power else 0.0,
            equity=float(account.portfolio_value) if account.portfolio_value else 0.0,
            currency="USD",
            account_id=str(account.id) if account.id else None,
        )

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        self._validate_order_inputs(ticker, quantity, order_type, price, stop_price)
        if self.dry_run:
            logger.info(
                "alpaca_dry_run_order",
                side=side.value,
                ticker=ticker,
                quantity=quantity,
                order_type=order_type.value,
            )
            return OrderResult(
                accepted=True,
                order_id=f"dryrun-{ticker}-{int(utc_now().timestamp() * 1000)}",
                state=OrderState.CREATED,
                message="Dry-run mode: order not sent to Alpaca.",
            )

        alpaca_side = AlpacaOrderSide.BUY if side is OrderSide.BUY else AlpacaOrderSide.SELL

        try:
            if order_type is OrderType.MARKET:
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=quantity,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                )
            elif order_type is OrderType.LIMIT and price is not None:
                req = LimitOrderRequest(
                    symbol=ticker,
                    qty=quantity,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=price,
                )
            else:
                return OrderResult(
                    accepted=False,
                    order_id="",
                    state=OrderState.REJECTED,
                    message=f"Unsupported order type or missing price: {order_type.value}",
                )

            result = self._client.submit_order(req)
            return OrderResult(
                accepted=True,
                order_id=str(result.client_order_id or result.id),
                broker_order_id=str(result.id),
                state=OrderState.SENT,
                raw_payload={"alpaca_status": result.status.value},
            )
        except APIError as exc:
            logger.error(
                "alpaca_place_order_failed",
                code=exc.status_code,
                message=str(exc),
            )
            return OrderResult(
                accepted=False,
                order_id="",
                state=OrderState.REJECTED,
                message=str(exc),
            )
        except Exception as exc:
            logger.error(
                "alpaca_place_order_error",
                error_type=type(exc).__name__,
                message=str(exc),
            )
            return OrderResult(
                accepted=False,
                order_id="",
                state=OrderState.REJECTED,
                message=str(exc),
            )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._client.cancel_order_by_id(order_id)
            return True
        except APIError:
            return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        order = self._client.get_order_by_id(order_id)
        return self._map_order_status(order)

    def get_open_orders(self) -> list[Order]:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        raw_orders = self._client.get_orders(filter=request)
        return [self._map_order(o) for o in raw_orders]

    @staticmethod
    def _map_order_status(order: Any) -> OrderStatus:
        return OrderStatus(
            order_id=str(order.client_order_id or order.id),
            broker_order_id=str(order.id),
            state=AlpacaBroker._map_state(order.status),
            filled_quantity=float(order.filled_qty) if order.filled_qty else 0.0,
            average_fill_price=float(order.filled_avg_price) if order.filled_avg_price else None,
            raw_payload={"alpaca_status": order.status.value},
        )

    @staticmethod
    def _map_order(order: Any) -> Order:
        side = OrderSide.BUY if order.side == AlpacaOrderSide.BUY else OrderSide.SELL
        order_type = OrderType.MARKET
        if hasattr(order, "type"):
            if order.type == AlpacaOrderType.LIMIT:
                order_type = OrderType.LIMIT
            elif order.type == AlpacaOrderType.STOP:
                order_type = OrderType.STOP
        return Order(
            ticker=str(order.symbol),
            side=side,
            quantity=float(order.qty) if order.qty else 0.0,
            order_type=order_type,
            price=float(order.limit_price) if hasattr(order, "limit_price") and order.limit_price else None,
            stop_price=float(order.stop_price) if hasattr(order, "stop_price") and order.stop_price else None,
            order_id=str(order.client_order_id or order.id),
            broker_order_id=str(order.id),
            state=AlpacaBroker._map_state(order.status),
            filled_quantity=float(order.filled_qty) if order.filled_qty else 0.0,
            average_fill_price=float(order.filled_avg_price) if order.filled_avg_price else None,
            created_at=order.created_at.astimezone(UTC) if hasattr(order, "created_at") and order.created_at else utc_now(),
        )

    @staticmethod
    def _map_state(status: Any) -> OrderState:
        value = status.value if hasattr(status, "value") else str(status)
        mapping = {
            AlpacaOrderStatus.NEW.value: OrderState.SENT,
            AlpacaOrderStatus.PARTIALLY_FILLED.value: OrderState.PARTIAL,
            AlpacaOrderStatus.FILLED.value: OrderState.FILLED,
            AlpacaOrderStatus.CANCELED.value: OrderState.CANCELLED,
            AlpacaOrderStatus.EXPIRED.value: OrderState.CANCELLED,
            AlpacaOrderStatus.REJECTED.value: OrderState.REJECTED,
        }
        return mapping.get(value.upper(), OrderState.SENT)
