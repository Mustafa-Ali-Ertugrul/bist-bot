from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional
from uuid import uuid4


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    CREATED = "created"
    SENT = "sent"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class BrokerOrder:
    ticker: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    order_id: str = field(default_factory=lambda: uuid4().hex)
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def remaining_quantity(self) -> float:
        return max(self.quantity - self.filled_quantity, 0.0)


@dataclass
class BrokerPosition:
    ticker: str
    quantity: float
    average_price: float
    opened_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class BaseBroker(ABC):
    """Common contract for paper and live execution providers."""

    @abstractmethod
    def get_account_balance(self) -> float:
        """Return currently available cash balance."""

    @abstractmethod
    def get_positions(self) -> dict[str, BrokerPosition]:
        """Return currently open positions keyed by ticker."""

    @abstractmethod
    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> BrokerOrder:
        """Submit an order and return the broker-side order model."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order if the broker still allows it."""
