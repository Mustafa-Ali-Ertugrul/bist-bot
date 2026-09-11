"""Regression tests proving cookie CSRF defense is armed and enforced (Round 20).

Flask-JWT-Extended is now configured with JWT_TOKEN_LOCATION=["headers", "cookies"]
and JWT_COOKIE_CSRF_PROTECT=True:

1. Bearer header auth on unsafe methods succeeds without CSRF headers
   (headers cannot be forged cross-site without CORS permission).
2. Cookie auth on unsafe methods (POST) without the X-CSRF-TOKEN double-submit
   header is REJECTED (401) by the middleware.
3. Cookie auth on unsafe methods with the matching X-CSRF-TOKEN header succeeds.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from flask import jsonify
from flask_jwt_extended import create_access_token, jwt_required, set_access_cookies

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

    @app.route("/api/__mint_test_cookies", methods=["GET"])
    def _mint():
        token = create_access_token(identity="42")
        resp = jsonify({"status": "minted"})
        set_access_cookies(resp, token)
        return resp

    @app.route("/api/__csrf_probe", methods=["POST"])
    @jwt_required()
    def _probe():
        return jsonify({"status": "ok"}), 200

    return app


def test_token_locations_include_both():
    """Config must explicitly allow headers and cookies for defense in depth."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        assert app.config["JWT_TOKEN_LOCATION"] == ["headers", "cookies"]
        assert app.config["JWT_COOKIE_CSRF_PROTECT"] is True


def test_bearer_header_post_does_not_need_csrf():
    """Header-authenticated API clients do not need a CSRF token."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        with app.app_context():
            token = create_access_token(identity="42")
        with app.test_client() as client:
            resp = client.post(
                "/api/__csrf_probe",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "ok"


def test_cookie_post_without_csrf_is_blocked():
    """Cookie-authenticated POST without X-CSRF-TOKEN must be rejected."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        with app.test_client() as client:
            client.get("/api/__mint_test_cookies")
            # POST with cookies in client jar, but NO X-CSRF-TOKEN header:
            resp = client.post("/api/__csrf_probe")
            assert resp.status_code in (400, 401, 403)
            assert resp.status_code != 200


def test_cookie_post_with_csrf_header_succeeds():
    """Cookie-authenticated POST with matching X-CSRF-TOKEN must pass."""
    with settings.override(
        JWT_SECRET_KEY=_JWT,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        app = _build_app()
        with app.test_client() as client:
            client.get("/api/__mint_test_cookies")
            csrf_token = client.get_cookie("csrf_access_token").value
            assert csrf_token, "set_access_cookies must emit csrf_access_token cookie"
            resp = client.post(
                "/api/__csrf_probe",
                headers={"X-CSRF-TOKEN": csrf_token},
            )
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "ok"
