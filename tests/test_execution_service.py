"""Execution service tests."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.services.execution_service import ExecutionService  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


def test_execution_service_uses_signal_position_size_for_broker_order():
    db = MagicMock()
    broker = MagicMock()
    broker.authenticate.return_value = True
    broker.place_order.return_value = MagicMock(
        state=MagicMock(value="SENT"), broker_order_id="BRK-1", order_id="ORD-1"
    )
    db.create_order.return_value = {"id": 11}
    service = ExecutionService(db, broker=broker, settings=settings.replace(AUTO_EXECUTE=True))
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        position_size=10,
    )

    service.auto_execute_signals([signal])

    db.create_order.assert_called_once_with(
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        state="CREATED",
    )
    assert broker.place_order.call_args.kwargs["quantity"] == 10.0
    db.update_order.assert_called_once_with(11, state="SENT", broker_order_id="BRK-1")


def test_execution_service_skips_when_position_size_is_zero():
    db = MagicMock()
    broker = MagicMock()
    broker.authenticate.return_value = True
    service = ExecutionService(db, broker=broker, settings=settings.replace(AUTO_EXECUTE=True))
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        position_size=0,
    )

    service.auto_execute_signals([signal])

    db.create_order.assert_not_called()
    broker.place_order.assert_not_called()
    db.update_order.assert_not_called()


def test_execute_signal_returns_attempt_on_success():
    """Phase 1: execute_signal returns ExecutionAttempt with accepted=True on FILLED."""
    db = MagicMock()
    broker = MagicMock()
    broker.authenticate.return_value = True
    broker.place_order.return_value = MagicMock(
        state=MagicMock(value="FILLED"),
        broker_order_id="BRK-1",
        order_id="ORD-1",
        accepted=True,
        average_fill_price=100.5,
    )
    db.create_order.return_value = {"id": 11}
    service = ExecutionService(db, broker=broker, settings=settings)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        position_size=10,
    )

    attempt = service.execute_signal(signal, force=True, require_fill=True)

    assert attempt is not None
    assert attempt.accepted is True
    assert attempt.order_db_id == 11
    assert attempt.state == "FILLED"
    assert attempt.fill_price == 100.5


def test_execute_signal_returns_rejected_on_broker_error():
    """Phase 1: execute_signal returns accepted=False on broker exception."""
    db = MagicMock()
    broker = MagicMock()
    broker.authenticate.return_value = True
    broker.place_order.side_effect = RuntimeError("connection lost")
    db.create_order.return_value = {"id": 22}
    service = ExecutionService(db, broker=broker, settings=settings)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        position_size=10,
    )

    attempt = service.execute_signal(signal, force=True, require_fill=True)

    assert attempt is not None
    assert attempt.accepted is False
    assert attempt.order_db_id == 22
    assert attempt.state == "REJECTED"
    assert attempt.error is not None


def test_execute_signal_rejected_state_returns_not_accepted():
    """Phase 1: broker returns REJECTED state → accepted=False."""
    db = MagicMock()
    broker = MagicMock()
    broker.authenticate.return_value = True
    broker.place_order.return_value = MagicMock(
        state=MagicMock(value="REJECTED"),
        broker_order_id=None,
        order_id="ORD-2",
        accepted=False,
        average_fill_price=None,
    )
    db.create_order.return_value = {"id": 33}
    service = ExecutionService(db, broker=broker, settings=settings)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        position_size=10,
    )

    attempt = service.execute_signal(signal, force=True, require_fill=True)

    assert attempt is not None
    assert attempt.accepted is False


def test_execute_signal_no_broker_returns_none():
    """Phase 1: no broker → execute_signal returns None."""
    db = MagicMock()
    service = ExecutionService(db, broker=None, settings=settings)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        position_size=10,
    )

    attempt = service.execute_signal(signal, force=True)

    assert attempt is None


def test_auto_execute_signals_returns_attempt_list():
    """Phase 1: auto_execute_signals returns list of ExecutionAttempt."""
    db = MagicMock()
    broker = MagicMock()
    broker.authenticate.return_value = True
    broker.place_order.return_value = MagicMock(
        state=MagicMock(value="FILLED"),
        broker_order_id="BRK-3",
        order_id="ORD-3",
        accepted=True,
        average_fill_price=100.0,
    )
    db.create_order.return_value = {"id": 44}
    service = ExecutionService(db, broker=broker, settings=settings.replace(AUTO_EXECUTE=True))
    signals = [
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.STRONG_BUY,
            score=80,
            price=100.0,
            position_size=10,
        ),
        Signal(
            ticker="ASELS.IS",
            signal_type=SignalType.STRONG_SELL,
            score=-80,
            price=50.0,
            position_size=20,
        ),
    ]

    attempts = service.auto_execute_signals(signals)

    assert len(attempts) == 2
    for a in attempts:
        assert hasattr(a, "accepted")
        assert hasattr(a, "order_db_id")
