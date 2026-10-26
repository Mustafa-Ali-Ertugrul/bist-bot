"""Faz P3.2: stock comparison service and API."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.stock_profile_service import StockProfileService

TODAY = date.today()


def _bars(ticker: str, start: float, step: float, count: int = 40) -> list[DailyBar]:
    out = []
    price = start
    for index in range(count):
        day = TODAY - timedelta(days=count - index)
        out.append(
            DailyBar(
                date=day,
                close=price,
                close_raw=price,
                market_cap_tl=price * 1_000_000,
                volume_tl=1_000_000.0,
            )
        )
        price = price + step
    return out


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "compare.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    repository.upsert_instruments(
        [
            Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Teknoloji"),
            Instrument(code="BBB", ticker="BBB.IS", name="B", sector="Sanayi"),
        ]
    )
    repository.write_bars("AAA.IS", _bars("AAA.IS", 100.0, 1.0), source="isyatirim")
    repository.write_bars("BBB.IS", _bars("BBB.IS", 50.0, -0.2), source="isyatirim")
    return repository


def test_compare_normalises_to_a_common_base(repo: MarketDataRepository) -> None:
    payload = StockProfileService(repo).compare(["AAA", "BBB"], range_key="1y")

    assert payload["base_date"]
    codes = [item["code"] for item in payload["stocks"]]
    assert codes == ["AAA", "BBB"]
    for item in payload["stocks"]:
        assert item["series"], "her hisse için normalize seri dönmeli"
        assert item["series"][0]["value"] == 100.0
    assert payload["missing"] == []


def test_compare_reports_unknown_codes(repo: MarketDataRepository) -> None:
    payload = StockProfileService(repo).compare(["AAA", "ZZZ"], range_key="1y")
    assert [item["code"] for item in payload["stocks"]] == ["AAA"]
    assert payload["missing"] == ["ZZZ"]


def test_compare_deduplicates_and_caps_codes(repo: MarketDataRepository) -> None:
    payload = StockProfileService(repo).compare(
        ["AAA", "AAA.IS", "BBB", "CCC", "DDD"], range_key="1y", max_codes=2
    )
    assert [item["code"] for item in payload["stocks"]] == ["AAA", "BBB"]


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "compare_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-compare-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        ALLOW_PUBLIC_REGISTRATION=True,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        market = MarketDataRepository(manager)
        market.upsert_instruments(
            [
                Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Teknoloji"),
                Instrument(code="BBB", ticker="BBB.IS", name="B", sector="Sanayi"),
            ]
        )
        market.write_bars("AAA.IS", _bars("AAA.IS", 100.0, 1.0), source="isyatirim")
        market.write_bars("BBB.IS", _bars("BBB.IS", 50.0, -0.2), source="isyatirim")
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=DataAccess(manager),
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["_test_manager"] = manager
        yield application


def _admin_headers(app: Flask, client, email: str = "cmp@bistbot.local") -> dict[str, Any]:
    client.post("/api/auth/register", json={"email": email, "password": "Str0ng-test-pass!"})
    token = client.post(
        "/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"}
    ).get_json()["access_token"]
    with app.config["_test_manager"].engine.begin() as conn:
        conn.execute(sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email})
    return {"Authorization": f"Bearer {token}"}


def test_compare_api_requires_auth(app: Flask) -> None:
    with app.test_client() as client:
        assert client.get("/api/stocks/compare?codes=AAA").status_code == 401


def test_compare_api_returns_stocks(app: Flask) -> None:
    with app.test_client() as client:
        headers = _admin_headers(app, client)
        resp = client.get("/api/stocks/compare?codes=AAA,BBB&range=1y", headers=headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert [item["code"] for item in body["stocks"]] == ["AAA", "BBB"]

        # The static /api/stocks/compare route must win over /api/stocks/<code>.
        assert body["status"] == "ok"


def test_compare_api_validates_input(app: Flask) -> None:
    with app.test_client() as client:
        headers = _admin_headers(app, client, "cmp2@bistbot.local")
        assert client.get("/api/stocks/compare", headers=headers).status_code == 400
        assert (
            client.get("/api/stocks/compare?codes=AAA,BBB,CCC,DDD,EEE", headers=headers).status_code
            == 400
        )
        assert client.get("/api/stocks/compare?codes=AAA&range=10y", headers=headers).status_code == 400
        assert client.get("/api/stocks/compare?codes=a;drop", headers=headers).status_code == 400


def test_compare_page_renders(app: Flask) -> None:
    with app.test_client() as client:
        _admin_headers(app, client, "cmppage@bistbot.local")
        resp = client.get("/ui/compare")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Hisse Karşılaştırma" in html
        assert "/static/compare.js" in html
        assert 'href="/ui/dashboard"' not in html
