"""Faz 7: legal pages/consent, KVKK export & deletion, entitlements, data gate."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask
from flask.testing import FlaskClient

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.entitlements import entitlements_for


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "commercial.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-commercial-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        STOCK_PAGES_PUBLIC=True,
        DATA_PUBLIC_SERVING_ENABLED=True,
        DATA_ATTRIBUTION="Veri: test sağlayıcı, gün sonu.",
        LEGAL_CONSENT_REQUIRED=False,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        market = MarketDataRepository(manager)
        market.upsert_instruments(
            [Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Test")]
        )
        market.write_bars(
            "AAA.IS",
            [DailyBar(date=date(2026, 10, 21), close=10.0, close_raw=10.0)],
            source="isyatirim",
        )
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=DataAccess(manager),
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["_test_manager"] = manager
        yield application


def _register(client: FlaskClient, email: str, accept: bool = True) -> dict[str, Any]:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Str0ng-test-pass!",
            "accept_terms": accept,
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()


def _promote(app: Flask, email: str) -> None:
    manager = app.config["_test_manager"]
    with manager.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )


# ---------------------------------------------------------------------------
# Legal documents and consent
# ---------------------------------------------------------------------------


def test_legal_pages_are_public_and_listed(app: Flask) -> None:
    with app.test_client() as client:
        documents = client.get("/api/legal/documents")
        assert documents.status_code == 200
        slugs = {item["slug"] for item in documents.get_json()["documents"]}
        assert {"kullanim-kosullari", "gizlilik", "kvkk-aydinlatma", "mesafeli-satis"} <= slugs

        for slug in slugs:
            page = client.get(f"/legal/{slug}")
            assert page.status_code == 200
            assert "TASLAK" in page.get_data(as_text=True)
        assert client.get("/legal/yok").status_code == 404


def test_registration_records_each_accepted_document(app: Flask) -> None:
    manager = app.config["_test_manager"]
    with app.test_client() as client:
        payload = _register(client, "consent@example.com")
        user_id = int(
            manager.run_session(
                lambda s: s.execute(
                    sa.text("SELECT id FROM users WHERE email='consent@example.com'")
                ).scalar(),
                read_only=True,
            )
        )
        rows = manager.run_session(
            lambda s: s.execute(
                sa.text(
                    "SELECT document, version FROM legal_acceptances WHERE user_id=:u ORDER BY document"
                ),
                {"u": user_id},
            ).all(),
            read_only=True,
        )
        assert len(rows) >= 4
        token = payload["access_token"]
        export = client.get(
            "/api/me/export", headers={"Authorization": f"Bearer {token}"}
        ).get_json()
        assert export["legal_acceptances"]


def test_registration_without_consent_when_required(app: Flask) -> None:
    with settings.override(LEGAL_CONSENT_REQUIRED=True):
        with app.test_client() as client:
            response = client.post(
                "/api/auth/register",
                json={"email": "noconsent@example.com", "password": "Str0ng-test-pass!"},
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# KVKK: export and deletion
# ---------------------------------------------------------------------------


def test_export_excludes_password_hash(app: Flask) -> None:
    with app.test_client() as client:
        payload = _register(client, "export@example.com")
        token = payload["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.post("/api/watchlists", headers=headers, json={"name": "Takip"})
        export = client.get("/api/me/export", headers=headers)
        assert export.status_code == 200
        body = export.get_json()
        assert body["user"]["email"] == "export@example.com"
        assert "password_hash" not in body["user"]
        assert body["watchlists"][0]["name"] == "Takip"


def test_account_deletion_removes_personal_rows(app: Flask) -> None:
    manager = app.config["_test_manager"]
    with app.test_client() as client:
        payload = _register(client, "delete@example.com")
        token = payload["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.post("/api/watchlists", headers=headers, json={"name": "Silinecek"})
        client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "change", "target": "AAA", "threshold": 5},
        )

        wrong = client.post(
            "/api/me/delete", headers=headers, json={"password": "yanlis-sifre-123"}
        )
        assert wrong.status_code == 401

        ok = client.post("/api/me/delete", headers=headers, json={"password": "Str0ng-test-pass!"})
        assert ok.status_code == 200

        counts = manager.run_session(
            lambda s: {
                "users": s.execute(sa.text("SELECT COUNT(*) FROM users")).scalar(),
                "watchlists": s.execute(sa.text("SELECT COUNT(*) FROM user_watchlists")).scalar(),
                "alerts": s.execute(sa.text("SELECT COUNT(*) FROM user_alerts")).scalar(),
            },
            read_only=True,
        )
        assert counts == {"users": 0, "watchlists": 0, "alerts": 0}
        # The JWT may still verify until it expires, but the account is gone.
        assert client.get("/api/me/export", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Entitlements and the public-data kill switch
# ---------------------------------------------------------------------------


def test_entitlements_scale_with_plan() -> None:
    free = entitlements_for({"role": "user", "plan": "trial", "plan_expires_at": None}, settings)
    paid = entitlements_for(
        {
            "role": "user",
            "plan": "pro",
            "plan_expires_at": "2099-01-01T00:00:00+00:00",
        },
        settings,
    )
    admin = entitlements_for({"role": "admin", "plan": "trial"}, settings)
    assert free.paid is False and free.screener_rows <= 5 and free.alerts < paid.alerts
    assert paid.paid is True and paid.screener_rows > free.screener_rows
    assert admin.screener_rows >= paid.screener_rows


def test_public_data_can_be_switched_off_for_members(app: Flask) -> None:
    with app.test_client() as client:
        payload = _register(client, "member@example.com")
        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        assert client.post("/api/screener/query", headers=headers, json={}).status_code == 200

        with settings.override(DATA_PUBLIC_SERVING_ENABLED=False):
            blocked = client.post("/api/screener/query", headers=headers, json={})
            assert blocked.status_code == 403

        _promote(app, "member@example.com")
        with settings.override(DATA_PUBLIC_SERVING_ENABLED=False):
            assert client.post("/api/screener/query", headers=headers, json={}).status_code == 200


def test_attribution_is_rendered_on_data_pages(app: Flask) -> None:
    with app.test_client() as client:
        payload = _register(client, "admin@example.com")
        _promote(app, "admin@example.com")
        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        page = client.get("/ui/stock/AAA", headers=headers)
        assert page.status_code == 200
        assert "Veri: test sağlayıcı" in page.get_data(as_text=True)
