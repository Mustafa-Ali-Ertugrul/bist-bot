"""Regression tests for the per-user rate-limit key (AppSec finding #21).

Behind Cloud Run every client shares the frontend proxy peer IP, so
get_remote_address() collapses all users into one shared bucket. The
default limiter key must therefore prefer the VERIFIED JWT identity and
only fall back to remote_addr for anonymous/invalid requests.
"""

from __future__ import annotations

import io
import os
import sys
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from flask_jwt_extended import create_access_token  # noqa: E402

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.dashboard import _client_rate_limit_key, create_dashboard_app  # noqa: E402

_JWT = "test-secret-health-check-fixture-0123456789"


def _build_app():
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=MagicMock(),
            broker=MagicMock(),
            circuit_breaker=MagicMock(),
        )
    app.config["TESTING"] = True
    return app


def _key_with_token(app, remote_addr: str, token: str | None) -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with app.test_request_context(
        "/api/analyze/ASELS",
        headers=headers,
        environ_overrides={"REMOTE_ADDR": remote_addr},
    ):
        return _client_rate_limit_key()


def test_valid_jwt_keys_per_identity_not_ip():
    """Verified identity wins: same IP, same identity → same bucket."""
    app = _build_app()
    with app.app_context():
        token = create_access_token(identity="42")
    key = _key_with_token(app, "10.0.0.1", token)
    assert key == "user:42"


def test_different_identities_same_ip_get_different_buckets():
    """The fix for finding #21: bucket separation no longer depends on IP."""
    app = _build_app()
    with app.app_context():
        token_a = create_access_token(identity="42")
        token_b = create_access_token(identity="43")
    key_a = _key_with_token(app, "10.0.0.1", token_a)
    key_b = _key_with_token(app, "10.0.0.1", token_b)
    assert key_a != key_b


def test_anonymous_falls_back_to_ip():
    """No token → remote_addr bucket (unchanged legacy behavior)."""
    app = _build_app()
    assert _key_with_token(app, "10.0.0.7", None) == "10.0.0.7"


def test_garbage_token_falls_back_to_ip_without_raising():
    """Invalid tokens must never raise inside the key function."""
    app = _build_app()
    key = _key_with_token(app, "10.0.0.7", "not-a-real-jwt")
    assert key == "10.0.0.7"


def test_expired_token_falls_back_to_ip_without_raising():
    """Expired tokens raise in verify_jwt_in_request — key must survive."""
    app = _build_app()
    with app.app_context():
        token = create_access_token(identity="42", expires_delta=timedelta(seconds=-1))
    key = _key_with_token(app, "10.0.0.7", token)
    assert key == "10.0.0.7"


def test_default_limiter_uses_client_key():
    """The Limiter's default key_func must be the identity-aware one."""
    app = _build_app()
    limiter = next(iter(app.extensions["limiter"]))  # flask-limiter stores a set
    assert limiter._key_func is _client_rate_limit_key


@pytest.mark.parametrize("hops", [0, 1])
def test_proxy_fix_gating(hops: int):
    """TRUSTED_PROXY_HOPS=0 keeps REMOTE_ADDR (spoof-proof default);
    =1 derives the rightmost XFF entry (real client behind Cloud Run)."""
    from bist_bot.wsgi import build_wsgi_app

    captured: dict[str, str] = {}

    def _factory():
        app = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=MagicMock(),
            broker=MagicMock(),
            circuit_breaker=MagicMock(),
        )

        @app.route("/__echo_remote_addr")
        def _echo():
            from flask import request

            captured["remote_addr"] = request.remote_addr or ""
            return "ok"

        return app

    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        TRUSTED_PROXY_HOPS=hops,
    ):
        app = build_wsgi_app(factory=_factory)

    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/__echo_remote_addr",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8080",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "localhost:8080",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "REMOTE_ADDR": "10.0.0.1",
        "HTTP_X_FORWARDED_FOR": "6.6.6.6, 8.8.8.8",
    }

    def _start_response(*args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    app(environ, _start_response)
    if hops == 0:
        assert captured["remote_addr"] == "10.0.0.1"
    else:
        assert captured["remote_addr"] == "8.8.8.8"
