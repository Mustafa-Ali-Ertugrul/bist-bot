"""Regression tests for the native Stitch UI routes (Flask /ui/* + /login)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from bist_bot.dashboard import create_dashboard_app


@pytest.fixture
def app() -> Flask:
    from bist_bot.config.settings import settings

    with settings.override(
        JWT_SECRET_KEY="test-secret",
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
    ):
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=MagicMock(),
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        return application


@pytest.mark.parametrize(
    "route",
    ["/login", "/ui", "/ui/dashboard", "/ui/signals", "/ui/analysis", "/ui/settings", "/"],
)
def test_stitch_ui_routes_return_html(app: Flask, route: str) -> None:
    with app.test_client() as client:
        resp = client.get(route)
        assert resp.status_code == 200
        assert "text/html" in (resp.content_type or "")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp


def test_stitch_static_assets_served(app: Flask) -> None:
    with app.test_client() as client:
        js = client.get("/static/app.js")
        assert js.status_code == 200
        assert len(js.data) > 1000
        css = client.get("/static/tailwind.css")
        assert css.status_code == 200
        assert len(css.data) > 1000
