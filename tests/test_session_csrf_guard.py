"""Regression tests for cookie-session CSRF resistance (Round 11).

INVARIANT: no cookie-authenticated unsafe route exists. /api/auth/session
mints the HttpOnly UI cookie but requires the Authorization Bearer header,
so a cross-site form/GET cannot trigger it (browsers cannot set custom
headers cross-origin). These tests lock that property in.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app

_JWT = "test-secret-health-check-fixture-0123456789"


def _build_app():
    app = create_dashboard_app(
        fetcher=MagicMock(),
        engine=MagicMock(),
        db=MagicMock(),
        broker=MagicMock(),
        circuit_breaker=MagicMock(),
    )
    app.config["TESTING"] = True
    return app


def test_session_mint_requires_bearer_header():
    """POST /api/auth/session without Authorization header must fail.

    A CSRF attacker cannot set the Authorization header cross-origin,
    so this guarantees the cookie-minting endpoint is not CSRF-triggerable.
    """
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        with app.test_client() as client:
            resp = client.post("/api/auth/session")
            assert resp.status_code == 401
            data = resp.get_json()
            assert "detail" not in data


def test_ui_pages_redirect_without_cookie():
    """GET /ui/dashboard without the auth cookie must 302 to /login."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        with app.test_client() as client:
            resp = client.get("/ui/dashboard", follow_redirects=False)
            assert resp.status_code == 302
            assert "/login" in resp.headers.get("Location", "")
