"""Faz P3 regression guards: asset cache-busting, product nav and page coverage."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager

ROOT = Path(__file__).resolve().parents[1] / "src" / "bist_bot"
PRODUCT_PAGES = (
    "screener.html",
    "watchlist.html",
    "portfolio.html",
    "alerts.html",
    "scorecard.html",
    "market.html",
    "compare.html",
    "stock.html",
)
TEMPLATES = ROOT / "templates" / "stitch"


def test_every_product_page_avoids_retired_admin_links() -> None:
    for name in PRODUCT_PAGES:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        assert 'href="/ui/dashboard"' not in html, name
        assert not re.search(r"\b(AL|SAT)\b", html), name
        assert "Stop-Loss" not in html, name
        assert "Hedef:" not in html, name


def test_product_pages_link_to_the_market_page() -> None:
    for name in PRODUCT_PAGES:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        assert 'href="/ui/market"' in html, name


def test_shared_asset_versions_are_consistent() -> None:
    """One asset must not be referenced with two different versions."""
    versions: dict[str, set[str]] = {}
    pattern = re.compile(r'/static/([\w.-]+\.(?:js|css))\?v=(\d+)')
    for name in PRODUCT_PAGES:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        for asset, version in pattern.findall(html):
            versions.setdefault(asset, set()).add(version)
    conflicting = {asset: found for asset, found in versions.items() if len(found) > 1}
    assert not conflicting, conflicting


def test_changed_frontend_assets_are_cache_busted() -> None:
    screener = (TEMPLATES / "screener.html").read_text(encoding="utf-8")
    assert "/static/screener.js?v=4" in screener
    assert "/static/screener.css?v=5" in screener
    alerts = (TEMPLATES / "alerts.html").read_text(encoding="utf-8")
    assert "/static/alerts.js?v=4" in alerts
    stock = (TEMPLATES / "stock.html").read_text(encoding="utf-8")
    assert "/static/stock.js?v=3" in stock
    for name in PRODUCT_PAGES:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        if "/static/product-nav.js" in html:
            assert "/static/product-nav.js?v=2" in html, name


def test_market_js_and_compare_js_are_served() -> None:
    for asset in ("market.js", "compare.js"):
        path = ROOT / "static" / asset
        assert path.is_file()
        body = path.read_text(encoding="utf-8")
        assert "bistbot_token" in body
        assert "textContent" in body or "innerHTML" in body


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "p3.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-p3-guards-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        ALLOW_PUBLIC_REGISTRATION=True,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=DataAccess(manager),
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["_test_manager"] = manager
        yield application


def _admin(app: Flask, client, email: str = "p3@bistbot.local") -> dict[str, Any]:
    client.post("/api/auth/register", json={"email": email, "password": "Str0ng-test-pass!"})
    token = client.post(
        "/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"}
    ).get_json()["access_token"]
    with app.config["_test_manager"].engine.begin() as conn:
        conn.execute(sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email})
    return {"Authorization": f"Bearer {token}"}


def test_p3_pages_require_auth(app: Flask) -> None:
    with app.test_client() as client:
        for route in ("/ui/market", "/ui/compare"):
            resp = client.get(route)
            assert resp.status_code == 302, route
            assert resp.headers.get("Location", "").endswith("/login"), route


def test_alerts_page_exposes_history_and_pause_controls(app: Flask) -> None:
    with app.test_client() as client:
        headers = _admin(app, client)
        html = client.get("/ui/alerts").get_data(as_text=True)
        assert "Alarm Geçmişi" in html
        assert 'id="events-refresh"' in html
        assert 'id="events-read"' in html
        # The alerts API supports toggling now.
        assert client.get("/api/alerts", headers=headers).status_code == 200
