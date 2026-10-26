"""Regression tests for Flask SECRET_KEY separation (Round 10).

The Flask session signing key must be separable from the JWT signing key.
An empty SECRET_KEY no longer reuses the JWT key verbatim: the dashboard
derives a stable, domain-separated key instead, so a value signed for one
purpose never verifies under the other.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from bist_bot.config.settings import settings
from bist_bot.dashboard import _derive_session_secret, create_dashboard_app

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


def test_secret_key_derived_and_separated_when_unset():
    """Empty SECRET_KEY derives a domain-separated key, never the JWT key."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        SECRET_KEY="",
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        assert app.config["SECRET_KEY"] == _derive_session_secret(_JWT)
        assert app.config["SECRET_KEY"] != _JWT
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
