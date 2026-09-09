"""Membership subscription: trial, gates, billing claims, admin approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from bist_bot.dashboard import create_dashboard_app

UTC = UTC


@pytest.fixture
def app(tmp_path) -> Flask:
    from bist_bot.config.settings import settings
    from bist_bot.db import DataAccess, DatabaseManager

    db_path = str(tmp_path / "subscription_test.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-subscription-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        RBAC_MODE="warn",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        TRIAL_HOURS=24,
        PRO_PRICE_TRY=500,
        PRO_PLUS_PRICE_TRY=700,
        SUBSCRIPTION_DAYS=30,
        GOOGLE_CLIENT_ID="test-google-client-id",
        GOOGLE_CLIENT_SECRET="test-google-client-secret",
        GOOGLE_REDIRECT_URI="http://localhost:5000/api/auth/google/callback",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        db = DataAccess(manager)
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=db,
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["SUB_TEST_DB_PATH"] = db_path
        yield application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _register(client: FlaskClient, email: str, password: str = "supersecretpw1") -> dict[str, Any]:
    reg = client.post("/api/auth/register", json={"email": email, "password": password})
    assert reg.status_code == 201, reg.get_data(as_text=True)
    return reg.get_json()


def _login(client: FlaskClient, email: str, password: str = "supersecretpw1") -> str:
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.get_data(as_text=True)
    return login.get_json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _db_manager(app: Flask):
    from bist_bot.db import DatabaseManager

    return DatabaseManager(sqlite_path=app.config["SUB_TEST_DB_PATH"])


def _set_expiry(
    app: Flask, email: str, expires_at: datetime | None, plan: str | None = None
) -> None:
    manager = _db_manager(app)
    with manager.engine.begin() as conn:
        if plan is None:
            conn.execute(
                text("UPDATE users SET plan_expires_at = :exp WHERE email = :email"),
                {"exp": expires_at, "email": email},
            )
        else:
            conn.execute(
                text("UPDATE users SET plan = :plan, plan_expires_at = :exp WHERE email = :email"),
                {"plan": plan, "exp": expires_at, "email": email},
            )


def _make_admin(app: Flask, email: str, password: str = "supersecretpw1") -> None:
    from bist_bot.auth.passwords import hash_password

    manager = _db_manager(app)
    now = datetime.now(UTC)
    with manager.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, password_hash, role, created_at, updated_at) "
                "VALUES (:email, :ph, 'admin', :now, :now)"
            ),
            {"email": email, "ph": hash_password(password), "now": now},
        )


# ---------------------------------------------------------------------------
# Registration + trial
# ---------------------------------------------------------------------------


def test_register_assigns_24h_trial(client: FlaskClient):
    _register(client, "trial1@example.com")
    # Inspect via a second connection through the app DB is complex; use login + subscription endpoint.
    token = _login(client, "trial1@example.com")
    res = client.get("/api/me/subscription", headers=_auth_headers(token))
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "active"
    assert data["plan"] == "trial"
    assert 23 * 3600 < data["remaining_seconds"] <= 24 * 3600


# ---------------------------------------------------------------------------
# Gate matrix
# ---------------------------------------------------------------------------


def test_gate_trial_active_allows_stats(client: FlaskClient):
    _register(client, "gate1@example.com")
    token = _login(client, "gate1@example.com")
    res = client.get("/api/stats", headers=_auth_headers(token))
    assert res.status_code == 200


def test_gate_expired_returns_402(client: FlaskClient, app: Flask):
    _register(client, "gate2@example.com")
    token = _login(client, "gate2@example.com")
    _set_expiry(app, "gate2@example.com", datetime.now(UTC) - timedelta(seconds=1))
    res = client.get("/api/stats", headers=_auth_headers(token))
    assert res.status_code == 402
    body = res.get_json()
    assert body["code"] == "sub_expired"
    res2 = client.get("/api/signals/history?limit=5", headers=_auth_headers(token))
    assert res2.status_code == 402


def test_gate_admin_bypass_without_plan(client: FlaskClient, app: Flask):
    _make_admin(app, "boss@example.com")
    token = _login(client, "boss@example.com")
    res = client.get("/api/stats", headers=_auth_headers(token))
    assert res.status_code == 200


def test_gate_unauthenticated_still_401(client: FlaskClient):
    res = client.get("/api/stats")
    assert res.status_code == 401


def test_me_subscription_shapes(client: FlaskClient, app: Flask):
    _register(client, "me1@example.com")
    token = _login(client, "me1@example.com")
    active = client.get("/api/me/subscription", headers=_auth_headers(token)).get_json()
    assert active["status"] == "active"
    assert set(active) >= {"status", "plan", "expires_at", "remaining_seconds", "remaining_days"}
    _set_expiry(app, "me1@example.com", datetime.now(UTC) - timedelta(seconds=1))
    expired = client.get("/api/me/subscription", headers=_auth_headers(token)).get_json()
    assert expired["status"] == "expired"
    assert expired["remaining_seconds"] == 0


def test_ui_expired_redirects_to_billing(client: FlaskClient, app: Flask):
    _register(client, "ui1@example.com")
    _login(client, "ui1@example.com")  # stores HttpOnly cookie in the test client
    _set_expiry(app, "ui1@example.com", datetime.now(UTC) - timedelta(seconds=1))
    res = client.get("/ui/dashboard")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/ui/billing")
    billing = client.get("/ui/billing")
    assert billing.status_code == 200


def test_ui_admin_gating(client: FlaskClient, app: Flask):
    _register(client, "plain@example.com")
    _login(client, "plain@example.com")
    res = client.get("/ui/admin")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/ui/dashboard")
    admin_client = app.test_client()
    _make_admin(app, "rooter@example.com")
    admin_login = admin_client.post(
        "/api/auth/login", json={"email": "rooter@example.com", "password": "supersecretpw1"}
    )
    assert admin_login.status_code == 200
    page = admin_client.get("/ui/admin")
    assert page.status_code == 200


# ---------------------------------------------------------------------------
# Billing claims
# ---------------------------------------------------------------------------


def test_claim_pro_creates_pending_with_backend_price(client: FlaskClient):
    _register(client, "pay1@example.com")
    token = _login(client, "pay1@example.com")
    # Attempted amount tampering must be ignored: backend prices authoritatively.
    res = client.post(
        "/api/billing/claim",
        headers=_auth_headers(token),
        json={"plan": "pro_plus", "amount_try": 1},
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["request"]["plan"] == "pro_plus"
    assert body["request"]["amount_try"] == 700
    assert body["request"]["status"] == "pending"
    assert body["request"]["reference"].startswith("BIST-")


def test_claim_duplicate_pending_returns_existing(client: FlaskClient):
    _register(client, "pay2@example.com")
    token = _login(client, "pay2@example.com")
    first = client.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "pro"})
    second = client.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "pro"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True
    assert second.get_json()["request"]["id"] == first.get_json()["request"]["id"]


def test_claim_invalid_plan_rejected(client: FlaskClient):
    _register(client, "pay3@example.com")
    token = _login(client, "pay3@example.com")
    res = client.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "trial"})
    assert res.status_code == 400
    res2 = client.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "admin"})
    assert res2.status_code == 400


# ---------------------------------------------------------------------------
# Admin RBAC + plan management + approval math
# ---------------------------------------------------------------------------


def _admin_client(app: Flask, email: str = "adminx@example.com") -> tuple[FlaskClient, str]:
    _make_admin(app, email)
    app.config["RBAC_MODE"] = "enforce"
    c = app.test_client()
    login = c.post("/api/auth/login", json={"email": email, "password": "supersecretpw1"})
    assert login.status_code == 200
    return c, login.get_json()["access_token"]


def test_admin_users_rbac(client: FlaskClient, app: Flask):
    _register(client, "nobody@example.com")
    token = _login(client, "nobody@example.com")
    app.config["RBAC_MODE"] = "enforce"
    assert client.get("/api/admin/users", headers=_auth_headers(token)).status_code == 403
    admin, atoken = _admin_client(app)
    res = admin.get("/api/admin/users", headers=_auth_headers(atoken))
    assert res.status_code == 200
    assert any(u["email"] == "nobody@example.com" for u in res.get_json()["users"])


def test_admin_set_plan_extends_remaining(app: Flask):
    _register(app.test_client(), "ext@example.com")
    admin, atoken = _admin_client(app, "admset@example.com")
    users = admin.get(
        "/api/admin/users?q=ext@example.com", headers=_auth_headers(atoken)
    ).get_json()["users"]
    uid = next(u["id"] for u in users if u["email"] == "ext@example.com")
    # First grant pro (fresh trial ~24h -> base is max(current, now) + 30d).
    r1 = admin.post(
        f"/api/admin/users/{uid}/plan", headers=_auth_headers(atoken), json={"plan": "pro"}
    )
    assert r1.status_code == 200
    first_exp = r1.get_json()["plan_expires_at"]
    # Second grant stacks on the remaining time.
    r2 = admin.post(
        f"/api/admin/users/{uid}/plan", headers=_auth_headers(atoken), json={"plan": "pro"}
    )
    assert r2.status_code == 200
    from datetime import datetime as _dt

    second_exp = r2.get_json()["plan_expires_at"]
    delta_days = (_dt.fromisoformat(second_exp) - _dt.fromisoformat(first_exp)).days
    assert delta_days == 30


def test_approve_flow_credits_30_days_and_decided_by(app: Flask):
    c = app.test_client()
    _register(c, "buyer@example.com")
    token = _login(c, "buyer@example.com")
    claim = c.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "pro"})
    rid = claim.get_json()["request"]["id"]
    admin, atoken = _admin_client(app, "approver@example.com")
    ok = admin.post(f"/api/admin/requests/{rid}/approve", headers=_auth_headers(atoken))
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["status"] == "ok"
    assert body["plan"] == "pro"
    # Second approval of the same request must fail atomically.
    again = admin.post(f"/api/admin/requests/{rid}/approve", headers=_auth_headers(atoken))
    assert again.status_code == 409
    # User is active with trial remainder stacked + 30 days (~31d for a fresh trial).
    sub = c.get("/api/me/subscription", headers=_auth_headers(token)).get_json()
    assert sub["status"] == "active" and sub["plan"] == "pro"
    assert 30 * 86400 < sub["remaining_seconds"] <= 31 * 86400 + 300
    reqs = admin.get(
        "/api/admin/requests?status=approved", headers=_auth_headers(atoken)
    ).get_json()["requests"]
    match = next(r for r in reqs if r["id"] == rid)
    assert match["decided_by"] is not None and match["decided_at"] is not None


def test_reject_flow(app: Flask):
    c = app.test_client()
    _register(c, "rejbuyer@example.com")
    token = _login(c, "rejbuyer@example.com")
    claim = c.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "pro"})
    rid = claim.get_json()["request"]["id"]
    admin, atoken = _admin_client(app, "rejecter@example.com")
    res = admin.post(f"/api/admin/requests/{rid}/reject", headers=_auth_headers(atoken))
    assert res.status_code == 200
    # Rejected user stays on trial (still active within 24h window).
    sub = c.get("/api/me/subscription", headers=_auth_headers(token)).get_json()
    assert sub["plan"] == "trial"
    again = admin.post(f"/api/admin/requests/{rid}/reject", headers=_auth_headers(atoken))
    assert again.status_code == 409


def test_approve_pro_plus_without_telegram_config_still_approves(app: Flask):
    c = app.test_client()
    _register(c, "plusbuyer@example.com")
    token = _login(c, "plusbuyer@example.com")
    claim = c.post("/api/billing/claim", headers=_auth_headers(token), json={"plan": "pro_plus"})
    rid = claim.get_json()["request"]["id"]
    admin, atoken = _admin_client(app, "plusapprover@example.com")
    ok = admin.post(f"/api/admin/requests/{rid}/approve", headers=_auth_headers(atoken))
    assert ok.status_code == 200
    assert "invite_link" not in ok.get_json()


# ---------------------------------------------------------------------------
# Google OAuth (mocked network)
# ---------------------------------------------------------------------------


def _google_login_redirect(client: FlaskClient) -> str:
    res = client.get("/api/auth/google/login")
    assert res.status_code == 302
    location = res.headers["Location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in location
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(location).query)["state"][0]


class _FakeResp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_google_callback_rejects_bad_state(client: FlaskClient):
    res = client.get("/api/auth/google/callback?code=abc&state=nope")
    assert res.status_code == 302
    assert res.headers["Location"].startswith("/login")


def test_google_full_flow_creates_trial_user(client: FlaskClient, monkeypatch):
    state = _google_login_redirect(client)

    def fake_post(url, data=None, timeout=None, **kwargs):
        assert "oauth2.googleapis.com/token" in url
        assert data["code"] == "valid-code"
        return _FakeResp(200, {"access_token": "ya29.test"})

    def fake_get(url, headers=None, timeout=None, **kwargs):
        assert "userinfo" in url
        return _FakeResp(
            200, {"sub": "google-123", "email": "guser@example.com", "email_verified": True}
        )

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    res = client.get(f"/api/auth/google/callback?code=valid-code&state={state}")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/ui/dashboard")
    assert "access_token_cookie=" in res.headers.get("Set-Cookie", "")
    # Reusing the same state must fail (single-use).
    res2 = client.get(f"/api/auth/google/callback?code=valid-code&state={state}")
    assert res2.status_code == 302
    assert res2.headers["Location"].startswith("/login")


def test_google_links_verified_email_account(client: FlaskClient, monkeypatch, app: Flask):
    _register(client, "linkme@example.com")

    def fake_post(url, data=None, timeout=None, **kwargs):
        return _FakeResp(200, {"access_token": "ya29.test"})

    def fake_get(url, headers=None, timeout=None, **kwargs):
        return _FakeResp(
            200, {"sub": "google-999", "email": "linkme@example.com", "email_verified": True}
        )

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    state = _google_login_redirect(client)
    res = client.get(f"/api/auth/google/callback?code=c2&state={state}")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/ui/dashboard")


def test_google_unverified_email_does_not_link(client: FlaskClient, monkeypatch):
    _register(client, "nolink@example.com")

    def fake_post(url, data=None, timeout=None, **kwargs):
        return _FakeResp(200, {"access_token": "ya29.test"})

    def fake_get(url, headers=None, timeout=None, **kwargs):
        return _FakeResp(
            200, {"sub": "google-000", "email": "nolink@example.com", "email_verified": False}
        )

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    state = _google_login_redirect(client)
    # Unverified email must neither attach to the existing password account
    # nor mint a duplicate-email identity: fail closed to login with error.
    res = client.get(f"/api/auth/google/callback?code=c3&state={state}")
    assert res.status_code == 302
    assert res.headers["Location"].startswith("/login")


# ---------------------------------------------------------------------------
# Telegram invite (mocked network)
# ---------------------------------------------------------------------------


def test_telegram_invite_success_and_failure(monkeypatch):
    from bist_bot import telegram_invite
    from bist_bot.config.settings import settings

    with settings.override(
        TELEGRAM_BOT_TOKEN="test-bot-token",
        TELEGRAM_PRO_CHANNEL_ID="@prokanal",
        TELEGRAM_INVITE_HOURS=48,
    ):

        def fake_post(url, json=None, timeout=None, **kwargs):
            assert "createChatInviteLink" in url
            assert json["member_limit"] == 1
            assert json["expire_date"] > 0
            return _FakeResp(200, {"ok": True, "result": {"invite_link": "https://t.me/+abc"}})

        monkeypatch.setattr(requests, "post", fake_post)
        assert telegram_invite.create_pro_invite_link() == "https://t.me/+abc"

        def fake_fail(url, json=None, timeout=None, **kwargs):
            return _FakeResp(400, {"ok": False, "description": "bot is not admin"})

        monkeypatch.setattr(requests, "post", fake_fail)
        assert telegram_invite.create_pro_invite_link() is None


# ---------------------------------------------------------------------------
# Migration 0006 shape
# ---------------------------------------------------------------------------


def test_migration_0006_subscription_columns(tmp_path):
    from pathlib import Path

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("dont_mutate_root_logger", "true")
    db_url = f"sqlite:///{(tmp_path / 'sub_mig.db').as_posix()}"
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")
    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        assert "payment_requests" in set(insp.get_table_names())
        user_cols = {c["name"] for c in insp.get_columns("users")}
        assert {"plan", "plan_expires_at", "trial_ends_at", "google_id"} <= user_cols
        pay_cols = {c["name"] for c in insp.get_columns("payment_requests")}
        assert {"user_id", "plan", "amount_try", "reference", "status", "decided_by"} <= pay_cols
