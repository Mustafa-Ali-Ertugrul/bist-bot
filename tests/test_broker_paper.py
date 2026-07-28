"""Paper broker and OrderExecutor unit/integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from bist_bot.broker import OrderExecutor, PaperBroker
from bist_bot.broker.base import Balance, OrderSide, OrderState, OrderType
from bist_bot.strategy.signal_models import Signal, SignalType


def test_paper_broker_market_buy_fills_and_updates_balance() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    result = broker.submit_order(
        ticker="SISE.IS",
        side="BUY",
        quantity=10,
        order_type="MARKET",
        price=50.0,
    )
    assert result.accepted is True
    assert result.state is OrderState.FILLED
    assert result.order_id

    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].ticker == "SISE.IS"
    assert positions[0].quantity == pytest.approx(10.0)

    bal = broker.get_balance()
    assert isinstance(bal, Balance)
    assert bal.cash < 100_000.0  # paid notional + fees
    assert bal.equity > 0


def test_paper_broker_sell_reduces_position() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    broker.submit_order("THYAO.IS", OrderSide.BUY, 20, OrderType.MARKET, price=100.0)
    broker.submit_order("THYAO.IS", OrderSide.SELL, 5, OrderType.MARKET, price=110.0)
    pos = broker.get_positions()
    assert len(pos) == 1
    assert pos[0].quantity == pytest.approx(15.0)


def test_paper_broker_cancel_open_limit_order() -> None:
    broker = PaperBroker(initial_cash=50_000.0, manual_confirm=True)
    result = broker.submit_order(
        "GARAN.IS", "BUY", 10, OrderType.LIMIT, price=80.0
    )
    assert result.state is OrderState.CREATED
    assert broker.cancel_order(result.order_id) is True
    status = broker.get_order_status(result.order_id)
    assert status.state is OrderState.CANCELLED


def test_paper_broker_get_order_status() -> None:
    broker = PaperBroker(initial_cash=10_000.0)
    result = broker.submit_order("PETKM.IS", "BUY", 2, "MARKET", price=25.0)
    status = broker.get_order_status(result.order_id)
    assert status.order_id == result.order_id
    assert status.state is OrderState.FILLED
    assert status.filled_quantity == pytest.approx(2.0)


def test_live_broker_rejects_unsupported_provider() -> None:
    from bist_bot.broker.live import LiveBroker

    mock_settings = MagicMock()
    with pytest.raises(ValueError, match="not supported by LiveBroker"):
        LiveBroker(provider="live", settings=mock_settings)
    with pytest.raises(ValueError, match="not supported by LiveBroker"):
        LiveBroker(provider="unknown", settings=mock_settings)


def test_order_executor_submits_buy_signal() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    settings = MagicMock()
    settings.AUTO_EXECUTE = True
    settings.AUTO_EXECUTE_WARN_MAX_QUANTITY = 100_000
    executor = OrderExecutor(broker, settings=settings, require_auto_execute=True)

    signal = Signal(
        ticker="SISE.IS",
        signal_type=SignalType.STRONG_BUY,
        score=55.0,
        price=40.0,
        position_size=10,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    result = executor.execute_signal(signal)
    assert result is not None
    assert result.accepted is True
    assert result.state is OrderState.FILLED
    assert broker.get_positions()[0].quantity == pytest.approx(10.0)


def test_order_executor_respects_auto_execute_flag() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    settings = MagicMock()
    settings.AUTO_EXECUTE = False
    executor = OrderExecutor(broker, settings=settings)
    signal = Signal(
        ticker="SISE.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=40.0,
        position_size=5,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    assert executor.execute_signal(signal) is None
    assert broker.get_positions() == []


def test_order_executor_force_bypasses_auto_execute_flag() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    settings = MagicMock()
    settings.AUTO_EXECUTE = False
    settings.AUTO_EXECUTE_WARN_MAX_QUANTITY = 100_000
    executor = OrderExecutor(broker, settings=settings)
    signal = Signal(
        ticker="TOASO.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=200.0,
        position_size=1,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    result = executor.execute_signal(signal, force=True)
    assert result is not None
    assert result.accepted is True


def test_order_executor_propagates_venue_failure() -> None:
    from bist_bot.broker.live import LiveBroker

    mock_settings = MagicMock()
    mock_settings.ALGOLAB_API_KEY = "k"
    mock_settings.ALGOLAB_USERNAME = "u"
    mock_settings.ALGOLAB_PASSWORD = "p"
    mock_settings.ALGOLAB_OTP_CODE = ""
    mock_settings.ALGOLAB_DRY_RUN = True

    mock_venue = MagicMock()
    mock_venue.place_order.return_value = MagicMock(accepted=False, state=OrderState.REJECTED, order_id="", message="API down")
    live = LiveBroker(provider="algolab", settings=mock_settings)
    live._venue = mock_venue  # inject mock venue

    executor = OrderExecutor(live, settings=MagicMock(AUTO_EXECUTE=True, AUTO_EXECUTE_WARN_MAX_QUANTITY=100_000))
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=60.0,
        price=300.0,
        position_size=1,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    result = executor.execute_signal(signal)
    assert result is not None
    assert result.accepted is False
    assert result.state is OrderState.REJECTED


def test_build_broker_paper_mode() -> None:
    pytest.importorskip("joblib")
    from bist_bot import dependencies as deps
    from bist_bot.broker.paper import PaperBroker as BP

    with deps.settings.override(BROKER_MODE="paper", BROKER_PROVIDER="paper"):
        broker = deps._build_broker()
    assert isinstance(broker, BP)


def test_build_broker_live_mode_rejects_unsupported_provider() -> None:
    pytest.importorskip("joblib")
    from bist_bot import dependencies as deps

    with deps.settings.override(BROKER_MODE="live", BROKER_PROVIDER="live"):
        with pytest.raises(ValueError, match="not supported by LiveBroker"):
            deps._build_broker()


def test_build_broker_live_mode_delegates_to_algolab() -> None:
    pytest.importorskip("joblib")
    from bist_bot import dependencies as deps
    from bist_bot.execution.algolab_broker import AlgoLabBroker

    with deps.settings.override(
        BROKER_MODE="live",
        BROKER_PROVIDER="algolab",
        ALGOLAB_API_KEY="test-key",
        ALGOLAB_USERNAME="test-user",
        ALGOLAB_PASSWORD="test-pass",
        ALGOLAB_OTP_CODE="",
        ALGOLAB_DRY_RUN=True,
    ):
        broker = deps._build_broker()
    assert isinstance(broker, AlgoLabBroker)


def test_build_broker_alpaca_provider_raises_removed() -> None:
    pytest.importorskip("joblib")
    from bist_bot import dependencies as deps

    with deps.settings.override(BROKER_MODE="paper", BROKER_PROVIDER="alpaca"):
        with pytest.raises(ValueError, match="Alpaca removed"):
            deps._build_broker()
