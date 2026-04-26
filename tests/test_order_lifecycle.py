"""Order lifecycle persistence and tracker tests."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.execution.base import OrderSide, OrderType  # noqa: E402
from bist_bot.execution.order_tracker import OrderTracker  # noqa: E402
from bist_bot.execution.paper_broker import PaperBroker  # noqa: E402


def test_order_lifecycle_created_to_sent_to_filled(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "orders.db"))
    db = DataAccess(manager)
    broker = PaperBroker(initial_cash=1_000)
    tracker = OrderTracker(broker, db, poll_interval_seconds=0.01)

    created = db.create_order(
        ticker="THYAO.IS",
        side=OrderSide.BUY.value,
        quantity=10,
        order_type=OrderType.LIMIT.value,
        price=100.0,
        state="CREATED",
    )
    assert created["state"] == "CREATED"

    order_result = broker.place_order(
        ticker="THYAO.IS",
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        price=100.0,
    )
    sent = db.update_order(
        created["id"], state=order_result.state.value, broker_order_id=order_result.order_id
    )
    assert sent is not None
    assert sent["state"] == "SENT"

    broker.fill_order(order_result.order_id, fill_price=100.0)
    tracker.poll_once()

    filled = db.get_order(created["id"])
    assert filled is not None
    assert filled["state"] == "FILLED"
    assert filled["filled_qty"] == 10.0
    assert filled["avg_fill_price"] == 100.0


def test_order_repository_preserves_created_quantity_and_updated_state(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "orders.db"))
    db = DataAccess(manager)

    created = db.create_order(
        ticker="ASELS.IS",
        side=OrderSide.SELL.value,
        quantity=7,
        order_type=OrderType.MARKET.value,
        price=None,
        state="CREATED",
    )
    updated = db.update_order(created["id"], state="REJECTED", broker_order_id="BRK-7")

    assert created["qty"] == 7
    assert updated is not None
    assert updated["qty"] == 7
    assert updated["state"] == "REJECTED"
    assert updated["broker_order_id"] == "BRK-7"
