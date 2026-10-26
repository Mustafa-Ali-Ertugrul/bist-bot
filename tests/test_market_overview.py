"""Faz P3.1: market overview service and API."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.market_overview_service import MarketOverviewService

AS_OF = date(2026, 10, 20)

CODES = ["AAA", "BBB", "CCC", "DDD"]


def _snapshot(ticker: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ticker": ticker,
        "close": 10.0,
        "change_pct": 1.0,
        "ret_1m": 2.0,
        "ret_3m": 3.0,
        "ret_1y": 4.0,
        "rsi14": 50.0,
        "sma50_gap_pct": 0.0,
        "sma200_gap_pct": 0.0,
        "from_52w_high_pct": -5.0,
        "avg_volume_20": 1_000_000.0,
        "market_cap_tl": 1_000_000_000.0,
        "pe_ttm": 8.0,
        "pb": 1.0,
        "net_margin_pct": 10.0,
        "roe_pct": 15.0,
        "sales_growth_yoy_pct": 25.0,
        "fundamentals_period": "2026/06",
    }
    row.update(overrides)
    return row


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "market.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    repository.upsert_instruments(
        [
            Instrument(
                code=code,
                ticker=f"{code}.IS",
                name=f"Şirket {code}",
                sector="Teknoloji" if index % 2 == 0 else "Sanayi",
            )
            for index, code in enumerate(CODES)
        ]
    )
    changes = [2.5, -1.5, 2.5, 0.0]
    rows = [
        _snapshot(
            f"{code}.IS",
            close=10.0 + index,
            change_pct=changes[index],
            ret_1m=float(index),
            avg_volume_20=1_000_000.0 * (index + 1),
        )
        for index, code in enumerate(CODES)
    ]
    repository.write_snapshots(AS_OF, rows)
    repository.replace_scan_results(
        "rsi_dip", AS_OF, [(f"{code}.IS", 20.0 + i, "RSI") for i, code in enumerate(CODES[:2])]
    )
    repository.write_benchmark_bars(
        "XU100", [(date(2026, 10, 19), 10000.0), (AS_OF, 10100.0)], source="test"
    )
    return repository


def test_overview_reports_breadth_leaders_and_sectors(repo: MarketDataRepository) -> None:
    payload = MarketOverviewService(repo).overview()

    assert payload["as_of"] == AS_OF.isoformat()
    breadth = payload["breadth"]
    assert breadth["total"] == 4
    assert breadth["advancers"] == 2
    assert breadth["decliners"] == 1
    assert breadth["unchanged"] == 1
    assert breadth["advancer_pct"] == 50.0

    index = payload["index"]
    assert index is not None
    assert index["code"] == "XU100"
    assert index["close"] == 10100.0
    assert index["change_pct"] == 1.0

    gainers = payload["leaders"]["gainers"]
    assert [row["code"] for row in gainers[:2]] == ["AAA", "CCC"]
    assert payload["leaders"]["losers"][0]["code"] == "BBB"
    assert payload["leaders"]["volume"][0]["code"] == "DDD"

    sectors = {item["sector"]: item for item in payload["sectors"]}
    assert set(sectors) == {"Teknoloji", "Sanayi"}
    assert sectors["Teknoloji"]["count"] == 2
    assert sectors["Teknoloji"]["avg_change_pct"] == 2.5

    scans = {item["code"]: item for item in payload["scans"]}
    assert scans["rsi_dip"]["count"] == 2


def test_overview_is_empty_without_snapshots(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "empty.db"))
    manager.initialize()
    payload = MarketOverviewService(MarketDataRepository(manager)).overview()

    assert payload["as_of"] is None
    assert payload["index"] is None
    assert payload["breadth"]["total"] == 0
    assert payload["leaders"] == {"gainers": [], "losers": [], "volume": []}
    assert payload["sectors"] == []
    assert payload["scans"] == []


def test_overview_respects_requested_limit(repo: MarketDataRepository) -> None:
    payload = MarketOverviewService(repo).overview(limit=1)
    assert len(payload["leaders"]["gainers"]) == 1


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "market_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-market-overview-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        ALLOW_PUBLIC_REGISTRATION=True,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        db = DataAccess(manager)
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=db,
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["_test_manager"] = manager
        yield application


def _register_admin(app: Flask, client, email: str) -> dict[str, Any]:
    import sqlalchemy as sa

    reg = client.post("/api/auth/register", json={"email": email, "password": "Str0ng-test-pass!"})
    assert reg.status_code == 201, reg.get_data(as_text=True)
    login = client.post("/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"})
    assert login.status_code == 200
    with app.config["_test_manager"].engine.begin() as conn:
        conn.execute(sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email})
    return login.get_json()


def test_market_overview_api_requires_auth(app: Flask) -> None:
    with app.test_client() as client:
        assert client.get("/api/market/overview").status_code == 401


def test_market_overview_api_returns_payload_for_admin(app: Flask) -> None:
    with app.test_client() as client:
        payload = _register_admin(app, client, "market@bistbot.local")
        resp = client.get(
            "/api/market/overview",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "breadth" in body and "leaders" in body


def test_market_page_renders_for_admin(app: Flask) -> None:
    with app.test_client() as client:
        _register_admin(app, client, "marketpage@bistbot.local")
        resp = client.get("/ui/market")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Piyasa Özeti" in html
        assert "/static/market.js" in html
        assert 'href="/ui/dashboard"' not in html
