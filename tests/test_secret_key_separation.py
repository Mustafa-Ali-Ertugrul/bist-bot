"""Regression tests for Flask SECRET_KEY separation (Round 10).

The Flask session signing key must be separable from the JWT signing key.
Empty SECRET_KEY preserves legacy fallback to JWT_SECRET_KEY.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app

_JWT = "test-secret-health-check-fixture-0123456789"
_SECRET = "distinct-flask-session-signing-key-0123456789abcdef"


def _build_app():
    return create_dashboard_app(
        fetcher=MagicMock(),
        engine=MagicMock(),
        db=MagicMock(),
        broker=MagicMock(),
        circuit_breaker=MagicMock(),
    )


def test_secret_key_falls_back_to_jwt_key_when_unset():
    """Legacy behavior preserved: empty SECRET_KEY falls back to JWT key."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        SECRET_KEY="",
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        assert app.config["SECRET_KEY"] == _JWT
        assert app.config["JWT_SECRET_KEY"] == _JWT


def test_secret_key_separated_when_set():
    """Distinct SECRET_KEY separates the Flask signing domain from JWT."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        SECRET_KEY=_SECRET,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        assert app.config["SECRET_KEY"] == _SECRET
        assert app.config["SECRET_KEY"] != app.config["JWT_SECRET_KEY"]
