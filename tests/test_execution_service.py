"""Execution service tests."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
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
    broker.place_order.return_value = MagicMock(state=MagicMock(value="SENT"), broker_order_id="BRK-1", order_id="ORD-1")
    db.create_order.return_value = {"id": 11}
    service = ExecutionService(db, broker=broker, settings=replace(settings, AUTO_EXECUTE=True))
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
    service = ExecutionService(db, broker=broker, settings=replace(settings, AUTO_EXECUTE=True))
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
