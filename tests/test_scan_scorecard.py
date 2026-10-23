"""Faz 8a: scan scorecard maths and API."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask
from flask.testing import FlaskClient

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.scan_scorecard_service import ScanScorecardService

D0 = date(2026, 1, 5)
D1 = date(2026, 1, 6)


def _seed(repo: MarketDataRepository) -> None:
    repo.upsert_instruments(
        [
            Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Test"),
            Instrument(code="BBB", ticker="BBB.IS", name="B", sector="Test"),
        ]
    )
    repo.write_bars(
        "AAA.IS",
        [
            DailyBar(date=D0, close=100.0, close_raw=100.0),
            DailyBar(date=D1, close=110.0, close_raw=110.0),
        ],
        source="isyatirim",
    )
    repo.write_bars(
        "BBB.IS",
        [
            DailyBar(date=D0, close=100.0, close_raw=100.0),
            DailyBar(date=D1, close=100.0, close_raw=100.0),
        ],
        source="isyatirim",
    )
    repo.write_benchmark_bars("XU100", [(D0, 1000.0), (D1, 1010.0)], source="isyatirim")
    repo.replace_scan_results(
        "rsi_dip",
        D0,
        [("AAA.IS", 20.0, "RSI"), ("ZZZ.IS", 18.0, "future data missing")],
    )


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "score.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    _seed(repository)
    return repository


def test_scorecard_compares_scan_with_index_and_random_basket(repo) -> None:
    payload = ScanScorecardService(repo).scorecard("rsi_dip", horizons=(1,))
    assert payload is not None
    score = payload["horizons"][0]
    assert score["observations"] == 1, "ZZZ has no future bar and must be skipped"
    assert score["scan_mean_pct"] == pytest.approx(10.0)
    assert score["xu100_mean_pct"] == pytest.approx(1.0)
    assert score["excess_vs_xu100_pct"] == pytest.approx(9.0)
    # Basket is deterministic: AAA (+10%) and BBB (0%) -> 5%.
    assert score["random_mean_pct"] == pytest.approx(5.0)
    assert score["excess_vs_random_pct"] == pytest.approx(5.0)
    assert score["reliable"] is False, "one observation is never evidence"
    assert score["win_rate_pct"] == pytest.approx(100.0)


def test_long_horizon_without_future_bars_is_empty(repo) -> None:
    payload = ScanScorecardService(repo).scorecard("rsi_dip", horizons=(60,))
    score = payload["horizons"][0]
    assert score["observations"] == 0
    assert score["scan_mean_pct"] is None
    assert score["t_stat"] is None


def test_unknown_scan_and_empty_history(repo) -> None:
    service = ScanScorecardService(repo)
    assert service.scorecard("nope") is None
    payload = service.scorecard("hacim_sok")
    assert payload is not None
    assert payload["horizons"] == []
    assert payload["note"]


def test_all_scorecards_covers_the_registry(repo) -> None:
    scores = ScanScorecardService(repo).all_scorecards(horizons=(1,))
    assert len(scores) == 8
    assert {item["scan_id"] for item in scores} >= {"rsi_dip", "ucuz_karli"}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "score_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-scorecard-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        STOCK_PAGES_PUBLIC=False,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        repository = MarketDataRepository(manager)
        _seed(repository)
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=DataAccess(manager),
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["_test_manager"] = manager
        yield application


def _login(client: FlaskClient, email: str = "member@bistbot.local") -> str:
    client.post("/api/auth/register", json={"email": email, "password": "Str0ng-test-pass!"})
    return client.post(
        "/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"}
    ).get_json()["access_token"]


def _promote(app: Flask, email: str) -> None:
    manager = app.config["_test_manager"]
    with manager.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )


def test_member_cannot_open_scorecard_when_private(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client)
        assert client.get("/ui/scorecard").status_code == 302
        assert (
            client.get("/api/scores", headers={"Authorization": f"Bearer {token}"}).status_code
            == 403
        )


def test_admin_gets_scorecard_payload_and_page(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin@bistbot.local")
        _promote(app, "admin@bistbot.local")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/ui/scorecard").status_code == 200

        payload = client.get("/api/scores?horizons=1", headers=headers)
        assert payload.status_code == 200
        scores = payload.get_json()["scores"]
        rsi = next(item for item in scores if item["scan_id"] == "rsi_dip")
        assert rsi["horizons"][0]["observations"] == 1

        one = client.get("/api/scores/rsi_dip?horizons=1", headers=headers)
        assert one.status_code == 200
        assert one.json["score"]["title"] == "RSI Dip"

        assert client.get("/api/scores/nope", headers=headers).status_code == 404
        assert client.get("/api/scores/rsi_dip?since=bozuk", headers=headers).status_code == 400
