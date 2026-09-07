"""Regression tests for the native Stitch UI routes (Flask /ui/* + /login).

The /ui/* HTML pages are server-side gated by the HttpOnly JWT cookie:
no cookie -> 302 to /login, valid cookie -> 200. /login stays public.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bist_bot.dashboard import create_dashboard_app

ACCESS_COOKIE = "access_token_cookie"
GATED_ROUTES = ["/", "/ui", "/ui/dashboard", "/ui/signals", "/ui/analysis", "/ui/settings"]
PUBLIC_ROUTES = ["/login", "/ui/login"]


@pytest.fixture
def app(tmp_path) -> Flask:
    from bist_bot.config.settings import settings
    from bist_bot.db import DataAccess, DatabaseManager

    db_path = str(tmp_path / "ui_routes_test.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-ui-routes-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
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
        yield application


def _register_and_login(client: FlaskClient, email: str, password: str) -> dict[str, Any]:
    reg = client.post("/api/auth/register", json={"email": email, "password": password})
    assert reg.status_code == 201, reg.get_data(as_text=True)
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.get_data(as_text=True)
    payload: dict[str, Any] = login.get_json()
    assert payload.get("access_token")
    return payload


@pytest.mark.parametrize("route", GATED_ROUTES)
def test_gated_routes_redirect_without_auth(app: Flask, route: str) -> None:
    with app.test_client() as client:
        resp = client.get(route)
        assert resp.status_code == 302
        assert resp.headers.get("Location", "").endswith("/login")


@pytest.mark.parametrize("route", PUBLIC_ROUTES)
def test_login_page_stays_public(app: Flask, route: str) -> None:
    with app.test_client() as client:
        resp = client.get(route)
        assert resp.status_code == 200
        assert "text/html" in (resp.content_type or "")


@pytest.mark.parametrize("route", GATED_ROUTES)
def test_authenticated_cookie_returns_html(app: Flask, route: str) -> None:
    with app.test_client() as client:
        _register_and_login(client, "ui@bistbot.local", "Str0ng-test-pass!")
        resp = client.get(route)
        assert resp.status_code == 200
        assert "text/html" in (resp.content_type or "")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp


@pytest.mark.parametrize("route", GATED_ROUTES)
def test_invalid_cookie_redirects_to_login(app: Flask, route: str) -> None:
    with app.test_client() as client:
        client.set_cookie(ACCESS_COOKIE, "garbage-not-a-jwt")
        resp = client.get(route)
        assert resp.status_code == 302
        assert resp.headers.get("Location", "").endswith("/login")


def test_login_sets_http_only_strict_cookie(app: Flask) -> None:
    with app.test_client() as client:
        reg = client.post(
            "/api/auth/register",
            json={"email": "cookie@bistbot.local", "password": "Str0ng-test-pass!"},
        )
        assert reg.status_code == 201
        login = client.post(
            "/api/auth/login", json={"email": "cookie@bistbot.local", "password": "Str0ng-test-pass!"}
        )
        assert login.status_code == 200
        set_cookies = login.headers.getlist("Set-Cookie")
        access = [c for c in set_cookies if c.startswith(f"{ACCESS_COOKIE}=")]
        assert access, f"access cookie missing in {set_cookies}"
        assert "HttpOnly" in access[0]
        assert "SameSite=Strict" in access[0]


def test_verify_endpoint_accepts_valid_bearer(app: Flask) -> None:
    with app.test_client() as client:
        payload = _register_and_login(client, "verify@bistbot.local", "Str0ng-test-pass!")
        resp = client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("valid") is True
        assert body.get("email") == "verify@bistbot.local"
        # The token itself must never be echoed back.
        assert "access_token" not in body


def test_verify_endpoint_rejects_bogus_or_missing_token(app: Flask) -> None:
    with app.test_client() as client:
        assert client.get("/api/auth/verify").status_code == 401
        # Malformed tokens get Flask-JWT-Extended's default 422 (same as /api/*).
        bad = client.get(
            "/api/auth/verify", headers={"Authorization": "Bearer bogus-token"}
        )
        assert bad.status_code == 422


def test_session_endpoint_mints_cookie_from_bearer(app: Flask) -> None:
    with app.test_client() as client:
        payload = _register_and_login(client, "session@bistbot.local", "Str0ng-test-pass!")
        resp = client.post(
            "/api/auth/session",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert resp.status_code == 200
        set_cookies = resp.headers.getlist("Set-Cookie")
        access = [c for c in set_cookies if c.startswith(f"{ACCESS_COOKIE}=")]
        assert access, f"access cookie missing in {set_cookies}"
        assert "HttpOnly" in access[0]


def test_session_endpoint_rejects_bogus_or_missing_token(app: Flask) -> None:
    with app.test_client() as client:
        assert client.post("/api/auth/session").status_code == 401
        bad = client.post(
            "/api/auth/session", headers={"Authorization": "Bearer bogus-token"}
        )
        assert bad.status_code == 422


def test_session_cookie_grants_gated_page_without_prior_login_cookie(app: Flask) -> None:
    """End-to-end bootstrap flow: Bearer -> session cookie -> gated page 200.

    Mirrors what the login page JS does, proving no redirect loop is needed.
    """
    with app.test_client() as naked_client:
        payload = _register_and_login(naked_client, "boot@bistbot.local", "Str0ng-test-pass!")
        # Drop every cookie to simulate "token in storage, no cookie" state.
        naked_client.delete_cookie(ACCESS_COOKIE)
        assert naked_client.get("/ui/dashboard").status_code == 302
        sess = naked_client.post(
            "/api/auth/session",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert sess.status_code == 200
        assert naked_client.get("/ui/dashboard").status_code == 200


def test_settings_html_contains_no_embedded_credentials(app: Flask) -> None:
    with app.test_client() as client:
        _register_and_login(client, "audit@bistbot.local", "Str0ng-test-pass!")
        resp = client.get("/ui/settings")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert not re.search(r'value="\d{6,}:[A-Za-z0-9_\-]{20,}"', body)
        assert not re.search(r'value="-\d{8,}"', body)


def test_stitch_static_assets_served(app: Flask) -> None:
    with app.test_client() as client:
        js = client.get("/static/app.js")
        assert js.status_code == 200
        assert len(js.data) > 1000
        body = js.get_data(as_text=True)
        # Login gate: unauthenticated visitors are bounced to /login.
        assert "bistbot_token" in body
        assert "window.location.replace('/login')" in body
        # Scan buttons surface real API outcomes (no fake success).
        assert "Oturum süresi doldu" in body
        assert "hydrateDashboardCounters" in body
        assert "totalPages()" in body
        css = client.get("/static/tailwind.css")
        assert css.status_code == 200
        assert len(css.data) > 1000
