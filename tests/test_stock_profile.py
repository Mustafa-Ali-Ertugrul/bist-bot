"""Faz 3: stock profile maths, persistence reads, API and page gating."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
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
from bist_bot.services.stock_profile_service import (
    StockProfileService,
    period_return,
    return_since,
    statement_view,
    ttm_value,
)

AS_OF = date(2026, 10, 20)


def _bars(closes: list[float], start: date = date(2026, 1, 1)) -> list[DailyBar]:
    return [
        DailyBar(
            date=start + timedelta(days=index),
            close=close,
            volume_tl=1_000.0 + index,
            market_cap_tl=1_000_000_000.0,
        )
        for index, close in enumerate(closes)
    ]


# ---------------------------------------------------------------------------
# Pure maths
# ---------------------------------------------------------------------------


def test_ttm_uses_previous_year_and_same_quarter() -> None:
    statements = {
        "2026/06": {"3C": 120.0, "3Z": 12.0},
        "2025/12": {"3C": 200.0, "3Z": 20.0},
        "2025/06": {"3C": 100.0, "3Z": 10.0},
    }
    assert ttm_value(statements, "3C") == pytest.approx(220.0)
    assert ttm_value(statements, "3Z") == pytest.approx(22.0)


def test_ttm_december_is_the_annual_value() -> None:
    statements = {"2025/12": {"3C": 200.0}}
    assert ttm_value(statements, "3C") == pytest.approx(200.0)


def test_ttm_returns_none_when_the_chain_is_incomplete() -> None:
    statements = {"2026/06": {"3C": 120.0}, "2025/12": {"3C": 200.0}}
    assert ttm_value(statements, "3C") is None


def test_statement_view_reports_latest_quarter_and_growth() -> None:
    statements = {
        "2026/06": {"3C": 120.0, "3Z": 12.0, "2O": 500.0},
        "2025/06": {"3C": 100.0, "3Z": 10.0, "2O": 450.0},
        "2025/12": {"3C": 200.0, "3Z": 20.0, "2O": 480.0},
    }
    view = statement_view(statements)
    assert view.latest_period == "2026/06"
    assert view.sales_growth_yoy_pct == pytest.approx(20.0)
    assert view.equity == pytest.approx(500.0)
    assert view.ttm_sales == pytest.approx(220.0)
    assert [row["period"] for row in view.quarters] == ["2025/06", "2025/12", "2026/06"]


def test_period_return_needs_enough_history() -> None:
    bars = _bars([10.0, 11.0, 12.0])
    assert period_return(bars, 2) == pytest.approx(20.0)
    assert period_return(bars, 5) is None


def test_return_since_uses_the_last_session_at_or_before_the_date() -> None:
    bars = _bars([10.0, 20.0, 30.0], start=date(2025, 12, 30))
    # 2025-12-31 close is 20.0; latest is 30.0.
    assert return_since(bars, date(2025, 12, 31)) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Service against a real sqlite repo
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "stock.db"))
    manager.initialize()
    return MarketDataRepository(manager)


def _seed(repo: MarketDataRepository, *, closes: list[float]) -> None:
    repo.upsert_instruments(
        [Instrument(code="THYAO", ticker="THYAO.IS", name="Türk Hava Yolları", sector="Ulaşım")]
    )
    repo.write_bars("THYAO.IS", _bars(closes), source="isyatirim")
    repo.write_statements(
        "THYAO.IS",
        {
            "2026/06": {"3C": 120.0, "3Z": 12.0, "2O": 500.0},
            "2025/12": {"3C": 200.0, "3Z": 20.0, "2O": 480.0},
            "2025/06": {"3C": 100.0, "3Z": 10.0, "2O": 450.0},
        },
    )


def test_profile_has_neutral_ratios_and_no_negative_pe(repo: MarketDataRepository) -> None:
    _seed(repo, closes=[10.0 + index for index in range(30)])
    profile = StockProfileService(repo).profile("THYAO")

    assert profile is not None
    assert profile["code"] == "THYAO"
    assert profile["as_of"] == "2026-01-30"
    assert profile["returns"]["1w"] is not None
    ratios = profile["fundamentals"]["ratios"]
    # Market cap 1e9 TL / TTM net profit (in thousands) -> absurd but positive PE.
    assert ratios["pe_ttm"] is not None and ratios["pe_ttm"] > 0
    assert ratios["net_margin_pct"] == pytest.approx(10.0)
    assert profile["technical"]["rsi14"] is not None


def test_profile_hides_pe_for_loss_making_company(repo: MarketDataRepository) -> None:
    _seed(repo, closes=[10.0] * 5)
    repo.write_statements("THYAO.IS", {"2025/12": {"3C": 100.0, "3Z": -5.0, "2O": 50.0}})
    profile = StockProfileService(repo).profile("THYAO")
    assert profile is not None
    assert profile["fundamentals"]["ratios"]["pe_ttm"] is None


def test_profile_returns_none_for_unknown_code(repo: MarketDataRepository) -> None:
    assert StockProfileService(repo).profile("NOPE") is None


def test_search_matches_code_and_name(repo: MarketDataRepository) -> None:
    _seed(repo, closes=[10.0])
    service = StockProfileService(repo)
    assert [item["code"] for item in service.search("thy")] == ["THYAO"]
    assert [item["code"] for item in service.search("hava")] == ["THYAO"]
    assert service.search("   ") == []


def test_scan_history_is_filtered_by_days(repo: MarketDataRepository) -> None:
    _seed(repo, closes=[10.0])
    repo.replace_scan_results("rsi_dip", AS_OF, [("THYAO.IS", 25.0, "RSI")])
    repo.replace_scan_results("hacim_sok", AS_OF - timedelta(days=60), [("THYAO.IS", 3.0, "Hacim")])
    hits = StockProfileService(repo).scans("THYAO", days=30)
    assert hits is not None
    assert [hit["scan_id"] for hit in hits] == ["rsi_dip"]


# ---------------------------------------------------------------------------
# HTTP: page + API gating
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "stock_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-stock-pages-123456",
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
        repo = MarketDataRepository(manager)
        _seed(repo, closes=[10.0 + index for index in range(30)])
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
    payload = client.post(
        "/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"}
    ).get_json()
    return payload["access_token"]


def _promote(app: Flask, email: str) -> None:
    manager = app.config["_test_manager"]
    with manager.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )


def test_member_is_redirected_from_stock_page(app: Flask) -> None:
    with app.test_client() as client:
        _login(client)
        resp = client.get("/ui/stock/THYAO")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/ui/beta")


def test_member_api_is_forbidden(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client)
        resp = client.get("/api/stocks/THYAO", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


def test_admin_gets_page_and_profile(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin@bistbot.local")
        _promote(app, "admin@bistbot.local")
        page = client.get("/ui/stock/THYAO")
        assert page.status_code == 200
        assert "lightweight-charts" in page.get_data(as_text=True)

        profile = client.get("/api/stocks/THYAO", headers={"Authorization": f"Bearer {token}"})
        assert profile.status_code == 200
        assert profile.get_json()["profile"]["code"] == "THYAO"

        bars = client.get(
            "/api/stocks/THYAO/bars?range=1y", headers={"Authorization": f"Bearer {token}"}
        )
        assert bars.status_code == 200 and bars.get_json()["bars"]


def test_invalid_and_unknown_codes(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin2@bistbot.local")
        _promote(app, "admin2@bistbot.local")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/stocks/@@@", headers=headers).status_code == 400
        assert client.get("/api/stocks/NOPE", headers=headers).status_code == 404
        assert client.get("/api/stocks/THYAO/bars?range=2y", headers=headers).status_code == 400


def test_search_and_no_advice_language(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin3@bistbot.local")
        _promote(app, "admin3@bistbot.local")
        resp = client.get("/api/stocks/search?q=thy", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.get_json()["results"][0]["code"] == "THYAO"

    root = Path(__file__).resolve().parents[1] / "src" / "bist_bot"
    for path in (root / "templates" / "stitch" / "stock.html", root / "static" / "stock.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(AL|SAT)\b", text), path.name
        assert "Stop-Loss" not in text, path.name
        assert "Hedef:" not in text, path.name
