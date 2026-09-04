from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

from flask_jwt_extended import create_access_token
from sqlalchemy import text

from bist_bot.auth.passwords import hash_password
from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager


class _Fetcher:
    watchlist: list[str] = []


class _Engine:
    pass


def _build_client(tmp_path):
    db_path = str(tmp_path / "scan_authz.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
        RBAC_MODE="warn",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        now = datetime.now(UTC)
        with manager.engine.begin() as conn:
            for email, role in (
                ("user@bistbot.local", "user"),
                ("trader@bistbot.local", "trader"),
                ("admin@bistbot.local", "admin"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO users "
                        "(email, password_hash, role, created_at, updated_at) "
                        "VALUES (:email, :password_hash, :role, :created_at, :updated_at)"
                    ),
                    {
                        "email": email,
                        "password_hash": hash_password("test-password"),
                        "role": role,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            rows = conn.execute(text("SELECT id, email, role FROM users")).mappings().all()
        users = {str(row["email"]): dict(row) for row in rows}

        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, _Fetcher()), cast(Any, _Engine()), db)
        app.config["TESTING"] = True
        app.config["RBAC_MODE"] = "enforce"
        scan_service = MagicMock()
        scan_service.scan_once.return_value = []
        scan_service.last_scan_stats = {"scanned": 0, "signals": 0, "actionable": 0}
        scan_service.last_rejection_breakdown = {}
        app.config["scan_service_factory"] = lambda: scan_service

        with app.app_context():
            tokens = {
                email: create_access_token(
                    identity=str(user["id"]),
                    additional_claims={"role": user["role"], "email": email},
                )
                for email, user in users.items()
            }
            tokens["legacy"] = create_access_token(identity="trader@bistbot.local")
        return app.test_client(), manager, users, tokens


def _scan(client, token: str):
    return client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})


def test_user_role_cannot_trigger_scan_in_enforce_mode(tmp_path) -> None:
    client, _manager, _users, tokens = _build_client(tmp_path)

    response = _scan(client, tokens["user@bistbot.local"])

    assert response.status_code == 403


def test_trader_role_can_trigger_scan_in_enforce_mode(tmp_path) -> None:
    client, _manager, _users, tokens = _build_client(tmp_path)

    response = _scan(client, tokens["trader@bistbot.local"])

    assert response.status_code == 200


def test_legacy_email_identity_token_returns_401_in_enforce_mode(tmp_path) -> None:
    client, _manager, _users, tokens = _build_client(tmp_path)

    response = _scan(client, tokens["legacy"])

    assert response.status_code == 401


def test_legacy_email_identity_token_returns_401_in_warn_mode(tmp_path) -> None:
    client, _manager, _users, tokens = _build_client(tmp_path)
    client.application.config["RBAC_MODE"] = "warn"

    response = _scan(client, tokens["legacy"])

    assert response.status_code == 401


def test_database_demotion_invalidates_existing_trader_token(tmp_path) -> None:
    client, manager, users, tokens = _build_client(tmp_path)
    with manager.engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET role = 'user' WHERE id = :id"),
            {"id": users["trader@bistbot.local"]["id"]},
        )

    response = _scan(client, tokens["trader@bistbot.local"])

    assert response.status_code == 403


def test_manual_order_resolution_requires_admin_and_strong_confirmation(tmp_path) -> None:
    client, manager, _users, tokens = _build_client(tmp_path)
    repository = DataAccess(manager).order_intents
    repository.create(
        client_id="unknown-order",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10,
        order_type="MARKET",
        price=None,
        stop_price=None,
    )
    repository.update("unknown-order", status="unknown")

    def _resolve(token: str, payload: dict):
        return client.post(
            "/api/orders/intents/unknown-order/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

    valid_reject = {
        "resolution": "rejected",
        "reason": "operator verified no broker order",
        "confirmed_in_broker_ui": True,
    }
    # Separation of duties: user and trader cannot release the money-safety lock.
    assert _resolve(tokens["user@bistbot.local"], valid_reject).status_code == 403
    assert _resolve(tokens["trader@bistbot.local"], valid_reject).status_code == 403
    # Weak confirmation is rejected even for admins.
    short_reason = dict(valid_reject, reason="too short")
    assert _resolve(tokens["admin@bistbot.local"], short_reason).status_code == 400
    unconfirmed = dict(valid_reject)
    unconfirmed.pop("confirmed_in_broker_ui")
    assert _resolve(tokens["admin@bistbot.local"], unconfirmed).status_code == 400
    ack_without_broker_id = {
        "resolution": "ack",
        "reason": "operator verified broker fill",
        "confirmed_in_broker_ui": True,
    }
    assert _resolve(tokens["admin@bistbot.local"], ack_without_broker_id).status_code == 400

    resolved = _resolve(tokens["admin@bistbot.local"], valid_reject)
    assert resolved.status_code == 200
    assert resolved.get_json()["lock_released"] is True
    assert repository.get_unresolved("THYAO.IS") is None

    repository.create(
        client_id="filled-order",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10,
        order_type="MARKET",
        price=None,
        stop_price=None,
    )
    repository.update("filled-order", status="unknown")
    acked = client.post(
        "/api/orders/intents/filled-order/resolve",
        headers={"Authorization": f"Bearer {tokens['admin@bistbot.local']}"},
        json={
            "resolution": "ack",
            "reason": "operator verified broker fill",
            "broker_order_id": "broker-123",
            "confirmed_in_broker_ui": True,
        },
    )
    assert acked.status_code == 200
    assert repository.get_unresolved("THYAO.IS") is None
    with manager.engine.connect() as conn:
        audit_events = {
            str(value)
            for value in conn.execute(
                text(
                    "SELECT event_type FROM audit_trail "
                    "WHERE event_type IN "
                    "('rbac_access_denied', 'rbac_access_granted', "
                    "'order_intent_manually_resolved')"
                )
            ).scalars()
        }
    assert audit_events == {
        "rbac_access_denied",
        "rbac_access_granted",
        "order_intent_manually_resolved",
    }


def test_warn_mode_user_scan_forces_auto_execute_off(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "warn-scan.db")
    captured_settings: list[Any] = []

    class _ScanService:
        last_scan_stats = {"scanned": 0, "signals": 0, "actionable": 0}
        last_rejection_breakdown: dict[str, Any] = {}

        def __init__(self, *_args, settings, **_kwargs) -> None:
            captured_settings.append(settings)

        def scan_once(self, **_kwargs):
            return []

    monkeypatch.setattr("bist_bot.dashboard.ScanService", _ScanService)
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
        RBAC_MODE="warn",
        AUTO_EXECUTE=True,
        AUTO_EXECUTE_ENABLED=True,
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        now = datetime.now(UTC)
        with manager.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users "
                    "(email, password_hash, role, created_at, updated_at) "
                    "VALUES (:email, :password_hash, 'user', :created_at, :updated_at)"
                ),
                {
                    "email": "warn-user@bistbot.local",
                    "password_hash": hash_password("test-password"),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            user_id = conn.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": "warn-user@bistbot.local"},
            ).scalar_one()
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, _Fetcher()), cast(Any, _Engine()), db)
        app.config["TESTING"] = True
        with app.app_context():
            token = create_access_token(
                identity=str(user_id),
                additional_claims={"role": "user", "email": "warn-user@bistbot.local"},
            )

        response = _scan(app.test_client(), token)

    assert response.status_code == 200
    assert len(captured_settings) == 1
    assert captured_settings[0].AUTO_EXECUTE is False
    assert captured_settings[0].AUTO_EXECUTE_ENABLED is False
