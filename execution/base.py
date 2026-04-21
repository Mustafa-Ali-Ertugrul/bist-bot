"""Execution provider contracts and shared order models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderState(StrEnum):
    CREATED = "CREATED"
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Position:
    ticker: str
    quantity: float
    average_price: float
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class AccountInfo:
    cash_balance: float
    buying_power: float
    equity: float
    currency: str = "TRY"
    account_id: str | None = None


@dataclass
class Order:
    ticker: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    price: float | None = None
    stop_price: float | None = None
    order_id: str = field(default_factory=lambda: uuid4().hex)
    broker_order_id: str | None = None
    state: OrderState = OrderState.CREATED
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def remaining_quantity(self) -> float:
        return max(self.quantity - self.filled_quantity, 0.0)


@dataclass
class OrderStatus:
    order_id: str
    state: OrderState
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    broker_order_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    accepted: bool
    order_id: str
    state: OrderState
    broker_order_id: str | None = None
    message: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)


class ExecutionProvider(Protocol):
    def authenticate(self) -> bool: ...
    def get_positions(self) -> list[Position]: ...
    def get_account_info(self) -> AccountInfo: ...
    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_order_status(self, order_id: str) -> OrderStatus: ...
    def get_open_orders(self) -> list[Order]: ...


class BaseExecutionProvider(ABC):
    """Shared execution provider base class."""

    @abstractmethod
    def authenticate(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        raise NotImplementedError

    @abstractmethod
    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        raise NotImplementedError

    @abstractmethod
    def get_open_orders(self) -> list[Order]:
        raise NotImplementedError
