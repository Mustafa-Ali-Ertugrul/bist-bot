"""Regression tests for auth rate-limit key binding (Round 17).

The login/register throttle MUST stay bound to the account email, not just
the client IP: behind Cloud Run all clients share the frontend peer IP
(IP collapse), and gunicorn never rewrites REMOTE_ADDR from
X-Forwarded-For (verified in installed gunicorn 26.x source — no ProxyFix
in this app), so the email component is the real per-account throttle.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bist_bot.config.settings import settings
from bist_bot.dashboard import _auth_rate_limit_key, create_dashboard_app

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


def _key_for(app, email: str, remote_addr: str) -> str:
    with app.test_request_context(
        "/api/auth/login",
        method="POST",
        json={"email": email, "password": "irrelevant-for-key"},
        environ_overrides={"REMOTE_ADDR": remote_addr},
    ):
        return _auth_rate_limit_key()


def test_rate_limit_key_binds_email_under_shared_ip():
    """Same frontend IP (Cloud Run collapse) + different emails → buckets.

    Without the email component every user would share one global bucket
    and one account's brute-forcing would be indistinguishable.
    """
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        key_a = _key_for(app, "alice@example.com", "10.0.0.1")
        key_b = _key_for(app, "bob@example.com", "10.0.0.1")
        assert key_a != key_b
        assert "alice@example.com" in key_a
        assert "bob@example.com" in key_b


def test_rate_limit_key_binds_ip_for_same_email():
    """Same email from different IPs → separate buckets (defense in depth
    where client IPs do differ, e.g. direct/local deployments)."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        key_a = _key_for(app, "alice@example.com", "10.0.0.1")
        key_b = _key_for(app, "alice@example.com", "10.0.0.2")
        assert key_a != key_b


def test_rate_limit_key_without_email_falls_back_to_ip():
    """Missing email still yields a stable IP-only bucket (no crash)."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        with app.test_request_context(
            "/api/auth/login",
            method="POST",
            json={},
            environ_overrides={"REMOTE_ADDR": "10.0.0.9"},
        ):
            assert _auth_rate_limit_key() == "10.0.0.9"
