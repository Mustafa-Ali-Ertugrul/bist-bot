"""LiveBroker delegation tests with mock venue adapters."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bist_bot.broker.live import LiveBroker, _resolve_venue
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
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> MagicMock:
    defaults = dict(
        ALGOLAB_API_KEY="key",
        ALGOLAB_USERNAME="user",
        ALGOLAB_PASSWORD="pass",
        ALGOLAB_OTP_CODE="",
        ALGOLAB_DRY_RUN=True,
    )
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


class MockVenue(BaseExecutionProvider):
    """Minimal in-memory venue for testing delegation."""

    def __init__(self, *, auth_ok: bool = True) -> None:
        self.auth_ok = auth_ok
        self.positions: list[Position] = []
        self.balance = AccountInfo(
            cash_balance=50_000.0,
            buying_power=100_000.0,
            equity=50_000.0,
            currency="TRY",
        )
        self.orders: dict[str, OrderResult] = {}
        self._next_id = 1

    def authenticate(self) -> bool:
        return self.auth_ok

    def get_positions(self) -> list[Position]:
        return list(self.positions)

    def get_account_info(self) -> AccountInfo:
        return self.balance

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        oid = f"mock-{self._next_id}"
        self._next_id += 1
        result = OrderResult(
            accepted=True,
            order_id=oid,
            state=OrderState.FILLED,
            broker_order_id=oid,
            message="filled",
        )
        self.orders[oid] = result
        return result

    def cancel_order(self, order_id: str) -> bool:
        return order_id in self.orders

    def get_order_status(self, order_id: str) -> OrderStatus:
        r = self.orders.get(order_id)
        if r is None:
            return OrderStatus(order_id=order_id, state=OrderState.REJECTED)
        return OrderStatus(
            order_id=r.order_id,
            state=r.state,
            filled_quantity=10.0,
            broker_order_id=r.broker_order_id,
        )

    def get_open_orders(self) -> list[Order]:
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveVenue:
    def test_algolab_returns_algolab_broker(self) -> None:
        from bist_bot.execution.algolab_broker import AlgoLabBroker

        venue = _resolve_venue("algolab", _make_settings())
        assert isinstance(venue, AlgoLabBroker)

    def test_alpaca_raises_removed_error(self) -> None:
        with pytest.raises(ValueError, match="not supported by LiveBroker"):
            _resolve_venue("alpaca", _make_settings())

    def test_unsupported_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported"):
            _resolve_venue("interactive_brokers", _make_settings())

    def test_live_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported"):
            _resolve_venue("live", _make_settings())


class TestLiveBrokerDelegation:
    def _make_broker(self, venue: MockVenue | None = None) -> tuple[LiveBroker, MockVenue]:
        mock_venue = venue or MockVenue()
        broker = LiveBroker.__new__(LiveBroker)
        broker._provider_name = "algolab"
        broker._venue = mock_venue
        return broker, mock_venue

    def test_authenticate_delegates(self) -> None:
        broker, _venue = self._make_broker()
        assert broker.authenticate() is True

    def test_authenticate_failure(self) -> None:
        broker, _ = self._make_broker(MockVenue(auth_ok=False))
        assert broker.authenticate() is False

    def test_get_positions_delegates(self) -> None:
        broker, venue = self._make_broker()
        venue.positions = [
            Position(ticker="X.IS", quantity=10, average_price=5.0, market_value=50.0)
        ]
        pos = broker.get_positions()
        assert len(pos) == 1
        assert pos[0].ticker == "X.IS"

    def test_get_account_info_delegates(self) -> None:
        broker, _ = self._make_broker()
        info = broker.get_account_info()
        assert info.cash_balance == pytest.approx(50_000.0)
        assert info.buying_power == pytest.approx(100_000.0)

    def test_place_order_delegates(self) -> None:
        broker, _ = self._make_broker()
        result = broker.place_order("THYAO.IS", OrderSide.BUY, 5, OrderType.MARKET)
        assert result.accepted is True
        assert result.state is OrderState.FILLED
        assert result.order_id.startswith("mock-")

    def test_cancel_order_delegates(self) -> None:
        broker, _venue = self._make_broker()
        r = broker.place_order("THYAO.IS", OrderSide.BUY, 1, OrderType.MARKET)
        assert broker.cancel_order(r.order_id) is True
        assert broker.cancel_order("nonexistent") is False

    def test_get_order_status_delegates(self) -> None:
        broker, _venue = self._make_broker()
        r = broker.place_order("THYAO.IS", OrderSide.BUY, 1, OrderType.MARKET)
        status = broker.get_order_status(r.order_id)
        assert status.state is OrderState.FILLED
        assert status.filled_quantity == pytest.approx(10.0)

    def test_get_order_status_unknown(self) -> None:
        broker, _ = self._make_broker()
        status = broker.get_order_status("ghost")
        assert status.state is OrderState.REJECTED

    def test_get_open_orders_delegates(self) -> None:
        broker, _ = self._make_broker()
        assert broker.get_open_orders() == []

    def test_provider_name_property(self) -> None:
        broker, _ = self._make_broker()
        assert broker.provider_name == "algolab"

    def test_venue_property(self) -> None:
        broker, venue = self._make_broker()
        assert broker.venue is venue


class TestLiveBrokerInitLogging:
    def test_init_logs_provider_and_venue_type(self) -> None:
        from unittest.mock import patch

        broker, _ = TestLiveBrokerDelegation()._make_broker()
        with patch("bist_bot.broker.live.logger") as mock_log:
            broker._venue = MockVenue()
            broker.authenticate()
        mock_log.info.assert_any_call(
            "live_broker_auth",
            provider="algolab",
            success=True,
        )


class TestLiveBrokerOrderLogging:
    def test_place_order_logs(self) -> None:
        from unittest.mock import patch

        broker, _ = TestLiveBrokerDelegation()._make_broker()
        with patch("bist_bot.broker.live.logger") as mock_log:
            broker.place_order("THYAO.IS", OrderSide.BUY, 5, OrderType.MARKET)
        mock_log.info.assert_any_call(
            "live_broker_order",
            provider="algolab",
            ticker="THYAO.IS",
            side="BUY",
            quantity=5,
            accepted=True,
            state="FILLED",
            order_id=mock_log.info.call_args_list[-1].kwargs.get("order_id", "mock-1"),
        )

    def test_cancel_order_logs(self) -> None:
        from unittest.mock import patch

        broker, _venue = TestLiveBrokerDelegation()._make_broker()
        r = broker.place_order("THYAO.IS", OrderSide.BUY, 1, OrderType.MARKET)
        with patch("bist_bot.broker.live.logger") as mock_log:
            broker.cancel_order(r.order_id)
        mock_log.info.assert_any_call(
            "live_broker_cancel",
            provider="algolab",
            order_id=r.order_id,
            cancelled=True,
        )

    def test_authenticate_logs(self) -> None:
        from unittest.mock import patch

        broker, _ = TestLiveBrokerDelegation()._make_broker()
        with patch("bist_bot.broker.live.logger") as mock_log:
            broker.authenticate()
        mock_log.info.assert_any_call(
            "live_broker_auth",
            provider="algolab",
            success=True,
        )
