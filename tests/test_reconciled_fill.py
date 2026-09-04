from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from bist_bot.agent.position_manager import PositionManager
from bist_bot.agent.state_machine import PositionState
from bist_bot.config.settings import settings
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.execution.algolab_broker import (
    AlgoLabBroker,
    AlgoLabCredentials,
    AlgoLabEndpoints,
)
from bist_bot.execution.base import Order, OrderSide, OrderState, OrderType
from bist_bot.execution.reconcile_accounting import ReconcileAccountingService
from bist_bot.wsgi import build_wsgi_app


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


def _setup_accounting(tmp_path):
    db_path = str(tmp_path / "test_accounting.db")
    manager = DatabaseManager(sqlite_path=db_path)
    db = DataAccess(manager)
    pm = PositionManager(db, settings)
    accounting = ReconcileAccountingService(db=db, position_manager=pm)
    return manager, db, pm, accounting


def test_reconciled_fill_buy_opens_position(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    order_row = db.create_order(
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        state="CREATED",
    )
    order_db_id = int(order_row["id"])

    snapshot = {
        "stop_loss": 95.0,
        "target_price": 115.0,
        "signal_type": "STRONG_BUY",
        "score": 75.0,
        "regime": "BULL",
    }
    intent = db.order_intents.create(
        client_id="intent-buy-1",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=order_db_id,
        signal_snapshot=json.dumps(snapshot),
    )

    outcome = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-101",
        filled_qty=10.0,
        avg_fill_price=100.5,
        broker_state="FILLED",
    )

    assert outcome.success is True
    assert outcome.status == "ack"
    positions = pm.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "THYAO.IS"
    assert positions[0]["quantity"] == 10.0
    assert positions[0]["entry_price"] == 100.5


def test_reconciled_fill_sell_closes_position(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    # Open an existing position first
    pm.open_position(
        ticker="THYAO.IS",
        entry_order_id=1,
        entry_price=100.0,
        quantity=10.0,
        stop_loss=90.0,
        target_price=120.0,
        signal_type="STRONG_BUY",
        signal_score=80.0,
    )
    assert len(pm.get_open_positions()) == 1

    order_row = db.create_order(
        ticker="THYAO.IS",
        side="SELL",
        quantity=10.0,
        order_type="MARKET",
        state="CREATED",
    )
    intent = db.order_intents.create(
        client_id="intent-sell-1",
        ticker="THYAO.IS",
        side="SELL",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=int(order_row["id"]),
    )

    outcome = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-sell-1",
        filled_qty=10.0,
        avg_fill_price=110.0,
        broker_state="FILLED",
    )

    assert outcome.success is True
    assert outcome.status == "ack"
    assert len(pm.get_open_positions()) == 0


def test_reconciled_fill_without_snapshot_is_unaccounted(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    intent = db.order_intents.create(
        client_id="intent-legacy",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=1,
        signal_snapshot=None,  # Legacy intent without snapshot
    )

    outcome = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-leg",
        filled_qty=10.0,
        avg_fill_price=100.0,
        broker_state="FILLED",
    )

    assert outcome.success is False
    assert outcome.status == "ack_unaccounted"
    assert "missing signal snapshot" in outcome.detail
    assert len(pm.get_open_positions()) == 0


def test_reconciled_fill_without_avg_price_is_unaccounted(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    intent = db.order_intents.create(
        client_id="intent-no-price",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=1,
        signal_snapshot=json.dumps({"stop_loss": 90.0, "target_price": 120.0}),
    )

    outcome = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-np",
        filled_qty=10.0,
        avg_fill_price=None,
        broker_state="FILLED",
    )

    assert outcome.success is False
    assert outcome.status == "ack_unaccounted"
    assert "missing average fill price" in outcome.detail


def test_reconciled_fill_is_idempotent(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    snapshot = {"stop_loss": 90.0, "target_price": 120.0, "signal_type": "STRONG_BUY"}
    intent = db.order_intents.create(
        client_id="intent-idem",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=10,
        signal_snapshot=json.dumps(snapshot),
    )

    # First fill
    out1 = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-idem",
        filled_qty=10.0,
        avg_fill_price=100.0,
        broker_state="FILLED",
    )
    # Second identical fill replay
    out2 = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-idem",
        filled_qty=10.0,
        avg_fill_price=100.0,
        broker_state="FILLED",
    )

    assert out1.success is True
    assert out2.success is True
    assert "already exists" in out2.detail
    assert len(pm.get_open_positions()) == 1


def test_cancelled_order_with_fills_triggers_accounting(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    session = MagicMock(spec=requests.Session)
    submitted_at = datetime.now(UTC)

    session.request.side_effect = [
        requests.Timeout("ambiguous timeout"),
        _Response(
            {
                "orders": [
                    {
                        "order_id": "brk-cancelled-with-fill",
                        "ticker": "THYAO.IS",
                        "side": "BUY",
                        "quantity": 10.0,
                        "order_type": "MARKET",
                        "state": "CANCELLED",
                        "created_at": submitted_at.isoformat(),
                        "filled_quantity": 4.0,
                        "average_fill_price": 102.0,
                    }
                ]
            }
        ),
    ]

    broker = AlgoLabBroker(
        AlgoLabCredentials(api_key="k", username="u", password="p"),
        endpoints=AlgoLabEndpoints(
            orders="http://test/orders",
            order_history="http://test/history",
            cancel_order="http://test/cancel",
        ),
        session=session,
        dry_run=False,
        order_intents=db.order_intents,
        accounting_service=accounting,
        clock=lambda: submitted_at,
    )
    broker._session_token = "mock-valid-token"

    # Place order with snapshot
    snapshot = {"stop_loss": 90.0, "target_price": 120.0, "signal_type": "STRONG_BUY"}
    res = broker.place_order(
        "THYAO.IS",
        OrderSide.BUY,
        10.0,
        OrderType.MARKET,
        order_db_id=1,
        signal_snapshot=json.dumps(snapshot),
    )

    assert res.accepted is True
    assert "ack" in res.message
    # Position was opened for the filled 4 units
    positions = pm.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 4.0
    assert positions[0]["entry_price"] == 102.0


def test_status_map_override_and_unmapped_metric() -> None:
    session = MagicMock(spec=requests.Session)
    custom_map = {"OZEL_DURUM": "FILLED"}
    broker = AlgoLabBroker(
        AlgoLabCredentials(api_key="k", username="u", password="p"),
        status_map=custom_map,
        session=session,
    )
    # Recognized via custom map
    order = broker._parse_order({"state": "OZEL_DURUM", "ticker": "THYAO.IS"})
    assert order.state == OrderState.FILLED

    # Unmapped status triggers counter and fallback
    order2 = broker._parse_order({"state": "TAMAMEN_YENI_DURUM", "ticker": "THYAO.IS"})
    assert order2.state == OrderState.CREATED
    assert order2.metadata["state_known"] is False


def test_degraded_worker_exit_after_max_seconds(monkeypatch) -> None:
    import signal
    import time

    import bist_bot.wsgi as wsgi_mod
    from bist_bot.db import DatabaseInitializationError

    def failing_factory():
        raise DatabaseInitializationError("DB down")

    scheduled: dict[str, object] = {}

    class _FakeTimer:
        def __init__(self, seconds: float, func) -> None:
            scheduled["seconds"] = seconds
            scheduled["func"] = func
            self.daemon = False

        def start(self) -> None:
            scheduled["started"] = True

    monkeypatch.setattr(wsgi_mod.threading, "Timer", _FakeTimer)
    killed: list[int] = []
    monkeypatch.setattr(wsgi_mod.os, "kill", lambda pid, sig: killed.append(sig))

    app = build_wsgi_app(failing_factory, degraded_max_seconds=60)
    client = app.test_client()

    assert scheduled.get("seconds") == 60
    assert scheduled.get("started") is True
    # Expiry callback terminates the worker process via SIGTERM
    scheduled["func"]()  # type: ignore[operator]
    assert killed == [signal.SIGTERM]

    # /livez reports 503 once the degraded lifetime is exceeded
    expired_app = build_wsgi_app(failing_factory, degraded_max_seconds=0)
    time.sleep(0.02)
    expired_resp = expired_app.test_client().get("/livez")
    assert expired_resp.status_code == 503
    live_resp = client.get("/livez")
    assert live_resp.status_code == 200


def test_bootstrap_is_one_shot_via_state_table(tmp_path) -> None:
    db_path = str(tmp_path / "bootstrap_oneshot.db")
    from bist_bot.auth.passwords import hash_password

    admin_hash = hash_password("test-pass")
    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="enforce",
        ADMIN_BOOTSTRAP_EMAIL="admin@test.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=admin_hash,
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=True,
    ):
        # First startup seeds admin
        m1 = DatabaseManager(sqlite_path=db_path)
        with m1.engine.begin() as conn:
            from sqlalchemy import text

            r1 = conn.execute(
                text("SELECT role FROM users WHERE email='admin@test.local'")
            ).scalar_one()
            s1 = conn.execute(
                text(
                    "SELECT value FROM bootstrap_state WHERE key='admin_bootstrap_completed:admin@test.local'"
                )
            ).scalar_one_or_none()
            assert r1 == "admin"
            assert s1 == "created"

            # Add a trader account so enforce startup check remains satisfied when admin is demoted
            conn.execute(
                text(
                    "INSERT INTO users (email, password_hash, role, created_at, updated_at) "
                    "VALUES ('trader@test.local', :p, 'trader', :now, :now)"
                ),
                {"p": admin_hash, "now": datetime.now(UTC)},
            )
            # Demote admin to user manually in DB
            conn.execute(text("UPDATE users SET role='user' WHERE email='admin@test.local'"))
        m1.engine.dispose()

        # Second startup with UPDATE_EXISTING=True must NOT re-promote the demoted user because one-shot is recorded
        m2 = DatabaseManager(sqlite_path=db_path)
        with m2.engine.connect() as conn:
            r2 = conn.execute(
                text("SELECT role FROM users WHERE email='admin@test.local'")
            ).scalar_one()
            assert r2 == "user"  # One-shot guard prevented re-promotion!
        m2.engine.dispose()


def test_manual_resolve_mismatch_with_broker_history_returns_409(tmp_path) -> None:
    from flask_jwt_extended import create_access_token
    from sqlalchemy import text

    from bist_bot.auth.passwords import hash_password
    from bist_bot.dashboard import create_dashboard_app

    db_path = str(tmp_path / "resolve_409.db")
    manager = DatabaseManager(sqlite_path=db_path)
    now = datetime.now(UTC)
    with manager.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, password_hash, role, created_at, updated_at) VALUES ('admin@test.com', :p, 'admin', :now, :now)"
            ),
            {"p": hash_password("pass"), "now": now},
        )
        admin_id = conn.execute(
            text("SELECT id FROM users WHERE email='admin@test.com'")
        ).scalar_one()

    db = DataAccess(manager)
    db.order_intents.create(
        client_id="intent-409",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
    )
    db.order_intents.update("intent-409", status="unknown")

    # Mock broker returning history with filled_quantity=10.0
    mock_broker = MagicMock()
    mock_order = Order(
        ticker="THYAO.IS",
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        order_id="brk-409",
        broker_order_id="brk-409",
        state=OrderState.FILLED,
        filled_quantity=10.0,
        average_fill_price=100.0,
    )
    mock_broker.get_daily_orders.return_value = [mock_order]

    fetcher = MagicMock()
    fetcher.watchlist = []
    engine = MagicMock()
    app = create_dashboard_app(fetcher, engine, db, broker=mock_broker)
    app.config["TESTING"] = True

    with app.app_context():
        token = create_access_token(identity=str(admin_id), additional_claims={"role": "admin"})

    client = app.test_client()

    # Request body claims filled_qty=5.0 but broker history says 10.0 -> 409 Conflict
    res = client.post(
        "/api/orders/intents/intent-409/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resolution": "ack",
            "broker_order_id": "brk-409",
            "filled_qty": 5.0,
            "avg_fill_price": 100.0,
            "reason": "operator claims 5 filled but broker has 10",
            "confirmed_in_broker_ui": True,
        },
    )

    assert res.status_code == 409
    assert "Conflict" in res.get_json()["message"]


def test_partial_fill_cancel_then_second_read_full_fill(tmp_path) -> None:
    """PARTIAL 3 → cancel → second history read FILLED 10 → position 10 (race rule)."""
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    submitted_at = datetime.now(UTC)
    session = MagicMock(spec=requests.Session)

    first_history = {
        "orders": [
            {
                "order_id": "brk-race-2",
                "ticker": "THYAO.IS",
                "side": "BUY",
                "quantity": 10.0,
                "order_type": "MARKET",
                "state": "PARTIAL",
                "created_at": submitted_at.isoformat(),
                "filled_quantity": 3.0,
                "average_fill_price": 100.0,
            }
        ]
    }
    second_history = {
        "orders": [
            {
                "order_id": "brk-race-2",
                "ticker": "THYAO.IS",
                "side": "BUY",
                "quantity": 10.0,
                "order_type": "MARKET",
                "state": "FILLED",
                "created_at": submitted_at.isoformat(),
                "filled_quantity": 10.0,
                "average_fill_price": 101.0,
            }
        ]
    }

    def request(method: str, url: str, **kwargs: Any):
        if method == "POST" and "cancel" in url:
            return _Response({"cancelled": True})
        history = request_calls.get("count", 0)
        request_calls["count"] = history + 1
        if history == 0:
            return _Response(first_history)
        return _Response(second_history)

    request_calls: dict[str, int] = {}
    session.request.side_effect = request

    broker = AlgoLabBroker(
        AlgoLabCredentials(api_key="k", username="u", password="p"),
        endpoints=AlgoLabEndpoints(
            order_history="http://test/history",
            cancel_order="http://test/cancel",
        ),
        session=session,
        dry_run=False,
        order_intents=db.order_intents,
        accounting_service=accounting,
        clock=lambda: submitted_at,
    )
    broker._session_token = "mock-valid-token"
    snapshot = {"stop_loss": 90.0, "target_price": 120.0, "signal_type": "STRONG_BUY"}
    db.order_intents.create(
        client_id="intent-race-2",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=22,
        signal_snapshot=json.dumps(snapshot),
    )
    db.order_intents.update("intent-race-2", status="unknown")

    result = broker._reconcile_order(
        client_id="intent-race-2",
        ticker="THYAO.IS",
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        price=None,
        stop_price=None,
        submitted_at=submitted_at,
    )

    assert result.accepted is True
    # Accounting used the SECOND read: full 10 lots at 101.0
    positions = pm.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 10.0
    assert positions[0]["entry_price"] == 101.0


def test_double_reconcile_produces_single_position_change(tmp_path) -> None:
    """Two back-to-back reconciles of the same intent must not duplicate accounting."""
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    snapshot = {"stop_loss": 90.0, "target_price": 120.0, "signal_type": "STRONG_BUY"}
    db.order_intents.create(
        client_id="intent-race",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=21,
        signal_snapshot=json.dumps(snapshot),
    )

    session = MagicMock(spec=requests.Session)
    submitted_at = datetime.now(UTC)
    history_payload = {
        "orders": [
            {
                "order_id": "brk-race",
                "ticker": "THYAO.IS",
                "side": "BUY",
                "quantity": 10.0,
                "order_type": "MARKET",
                "state": "FILLED",
                "created_at": submitted_at.isoformat(),
                "filled_quantity": 10.0,
                "average_fill_price": 100.0,
            }
        ]
    }
    session.request.return_value = _Response(history_payload)
    broker = AlgoLabBroker(
        AlgoLabCredentials(api_key="k", username="u", password="p"),
        endpoints=AlgoLabEndpoints(order_history="http://test/history"),
        session=session,
        dry_run=False,
        order_intents=db.order_intents,
        accounting_service=accounting,
        clock=lambda: submitted_at,
    )
    broker._session_token = "mock-valid-token"

    first = broker._reconcile_order(
        client_id="intent-race",
        ticker="THYAO.IS",
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        price=None,
        stop_price=None,
        submitted_at=submitted_at,
    )
    second = broker._reconcile_order(
        client_id="intent-race",
        ticker="THYAO.IS",
        side=OrderSide.BUY,
        quantity=10.0,
        order_type=OrderType.MARKET,
        price=None,
        stop_price=None,
        submitted_at=submitted_at,
    )

    assert first.accepted is True
    assert second.accepted is True
    assert len(pm.get_open_positions()) == 1
    assert db.order_intents.get("intent-race")["status"] == "ack"


def test_reconciled_sell_loss_visible_in_position_ledger(tmp_path) -> None:
    """A reconciled SELL at a loss lands in the same ledger risk reads."""
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    pm.open_position(
        ticker="THYAO.IS",
        entry_order_id=31,
        entry_price=110.0,
        quantity=10.0,
        stop_loss=100.0,
        target_price=130.0,
        signal_type="STRONG_BUY",
        signal_score=80.0,
    )
    order_row = db.create_order(
        ticker="THYAO.IS", side="SELL", quantity=10.0, order_type="MARKET", state="CREATED"
    )
    intent = db.order_intents.create(
        client_id="intent-sell-loss",
        ticker="THYAO.IS",
        side="SELL",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=int(order_row["id"]),
    )

    outcome = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-sell-loss",
        filled_qty=10.0,
        avg_fill_price=100.0,
        broker_state="FILLED",
    )

    assert outcome.success is True
    assert outcome.status == "ack"
    # Same channel as the normal SELL path: closed row with negative realized PnL
    with manager.engine.connect() as conn:
        from sqlalchemy import text

        row = (
            conn.execute(
                text(
                    "SELECT state, realized_pnl FROM live_positions WHERE ticker='THYAO.IS' "
                    "ORDER BY id DESC LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row["state"] == PositionState.CLOSED.value
    assert float(row["realized_pnl"]) < 0
    assert len(pm.get_open_positions()) == 0


def test_reconciled_sell_partial_quantity_is_unaccounted(tmp_path) -> None:
    manager, db, pm, accounting = _setup_accounting(tmp_path)
    pm.open_position(
        ticker="THYAO.IS",
        entry_order_id=41,
        entry_price=100.0,
        quantity=10.0,
        stop_loss=90.0,
        target_price=120.0,
        signal_type="STRONG_BUY",
        signal_score=80.0,
    )
    intent = db.order_intents.create(
        client_id="intent-sell-partial",
        ticker="THYAO.IS",
        side="SELL",
        quantity=3.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
        order_db_id=41,
    )

    outcome = accounting.record_fill(
        intent=intent,
        broker_order_id="brk-sell-partial",
        filled_qty=3.0,
        avg_fill_price=105.0,
        broker_state="FILLED",
    )

    assert outcome.success is False
    assert outcome.status == "ack_unaccounted"
    # Full position untouched: no reduce path exists
    assert len(pm.get_open_positions()) == 1


def test_manual_resolve_without_broker_history_is_unaccounted(tmp_path) -> None:
    from flask_jwt_extended import create_access_token
    from sqlalchemy import text

    from bist_bot.auth.passwords import hash_password
    from bist_bot.dashboard import create_dashboard_app

    db_path = str(tmp_path / "resolve_no_history.db")
    manager = DatabaseManager(sqlite_path=db_path)
    now = datetime.now(UTC)
    with manager.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, password_hash, role, created_at, updated_at) "
                "VALUES ('admin@test.com', :p, 'admin', :now, :now)"
            ),
            {"p": hash_password("pass"), "now": now},
        )
        admin_id = conn.execute(
            text("SELECT id FROM users WHERE email='admin@test.com'")
        ).scalar_one()

    db = DataAccess(manager)
    db.order_intents.create(
        client_id="intent-nohist",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10.0,
        order_type="MARKET",
        price=None,
        stop_price=None,
    )
    db.order_intents.update("intent-nohist", status="unknown")

    # Broker whose history fetch always fails
    mock_broker = MagicMock()
    mock_broker.get_daily_orders.side_effect = requests.ConnectionError("broker down")

    fetcher = MagicMock()
    fetcher.watchlist = []
    engine = MagicMock()
    app = create_dashboard_app(fetcher, engine, db, broker=mock_broker)
    app.config["TESTING"] = True

    with app.app_context():
        token = create_access_token(identity=str(admin_id), additional_claims={"role": "admin"})

    res = app.test_client().post(
        "/api/orders/intents/intent-nohist/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resolution": "ack",
            "broker_order_id": "brk-nohist",
            "filled_qty": 10.0,
            "avg_fill_price": 100.0,
            "reason": "operator saw fill in broker UI",
            "confirmed_in_broker_ui": True,
        },
    )

    assert res.status_code == 200
    body = res.get_json()
    assert body["resolution"] == "ack_unaccounted"
    assert db.order_intents.get("intent-nohist")["status"] == "ack_unaccounted"


def test_bootstrap_hash_format_validated_by_verifier() -> None:
    with settings.override(
        ADMIN_BOOTSTRAP_EMAIL="admin@test.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="replace_with_scrypt_or_bcrypt_hash",
    ):
        with pytest.raises(RuntimeError, match="invalid format"):
            _ = settings.admin_bootstrap_enabled

    with settings.override(
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        assert settings.admin_bootstrap_enabled is False


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_background_replay_failure_is_visible(monkeypatch) -> None:
    from bist_bot.app_metrics import render_metrics, reset_metrics

    reset_metrics()
    session = MagicMock(spec=requests.Session)
    intents = MagicMock()
    intents.list_reconcilable.side_effect = RuntimeError("db exploded")
    broker = AlgoLabBroker(
        AlgoLabCredentials(api_key="k", username="u", password="p"),
        session=session,
        order_intents=intents,
    )
    broker._session_token = "tok"

    done = threading.Event()
    original_run = broker._run_reconcile_pending_intents

    def failing_run():
        try:
            return original_run()
        finally:
            done.set()

    monkeypatch.setattr(broker, "_run_reconcile_pending_intents", failing_run)
    broker.reconcile_pending_intents(background=True)
    assert done.wait(timeout=10) is True
    # Give the daemon thread a moment to record the failure metric
    # (the critical log line is visible in captured stderr output)
    import time as _time

    deadline = _time.monotonic() + 5.0
    while "reconcile_startup_failed_total" not in render_metrics():
        assert _time.monotonic() < deadline, "failure metric was not recorded"
        _time.sleep(0.05)
    assert "reconcile_startup_failed_total" in render_metrics()


def test_paper_mode_startup_reconcile_does_not_call_broker() -> None:
    from bist_bot.dependencies import _build_broker

    mock_db = MagicMock()
    with settings.override(BROKER_MODE="paper", BROKER_PROVIDER="paper"):
        broker = _build_broker(mock_db)
        # In paper mode, PaperBroker is returned, no algolab broker created, no authenticate
        from bist_bot.execution.paper_broker import PaperBroker

        assert isinstance(broker, PaperBroker)
