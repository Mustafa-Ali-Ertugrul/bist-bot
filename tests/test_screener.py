"""Faz 4: screener catalog, snapshots, filter validation and API limits."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask
from flask.testing import FlaskClient

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.screener_service import (
    MAX_CONDITIONS,
    ScreenerError,
    ScreenerService,
    matches,
    parse_conditions,
)

AS_OF = date(2026, 10, 20)

CODES = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]


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
    manager = DatabaseManager(sqlite_path=str(tmp_path / "screener.db"))
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
    rows = [
        _snapshot(
            f"{code}.IS",
            close=10.0 + index,
            rsi14=20.0 + index * 5,
            pe_ttm=5.0 + index,
            market_cap_tl=1_000_000_000.0 * (index + 1),
        )
        for index, code in enumerate(CODES)
    ]
    repository.write_snapshots(AS_OF, rows)
    repository.replace_scan_results(
        "rsi_dip", AS_OF, [(f"{code}.IS", 20.0 + i, "RSI") for i, code in enumerate(CODES[:3])]
    )
    return repository


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_parse_conditions_accepts_valid_input() -> None:
    parsed = parse_conditions(
        [
            {"field": "rsi14", "op": "<", "value": "30"},
            {"field": "pe_ttm", "op": "between", "value": 10, "value2": 2},
        ]
    )
    assert parsed[0] == {"field": "rsi14", "op": "<", "value": 30.0}
    # between swaps reversed bounds instead of returning nothing
    assert parsed[1]["value"] == 2.0 and parsed[1]["value2"] == 10.0


@pytest.mark.parametrize(
    "payload",
    [
        [{"field": "close; drop table users", "op": "<", "value": 1}],
        [{"field": "close", "op": "=", "value": 1}],
        [{"field": "close", "op": "<", "value": "abc"}],
        [{"field": "close", "op": "<", "value": "nan"}],
        "not-a-list",
    ],
)
def test_parse_conditions_rejects_bad_input(payload) -> None:
    with pytest.raises(ScreenerError):
        parse_conditions(payload)


def test_condition_count_is_capped() -> None:
    with pytest.raises(ScreenerError):
        parse_conditions([{"field": "close", "op": "<", "value": 1}] * (MAX_CONDITIONS + 1))


def test_matches_treats_missing_values_as_no_match() -> None:
    assert matches({"rsi14": 25.0}, [{"field": "rsi14", "op": "<", "value": 30}])
    assert not matches({"rsi14": None}, [{"field": "rsi14", "op": "<", "value": 30}])
    assert matches({"pe_ttm": 5.0}, [{"field": "pe_ttm", "op": "between", "value": 2, "value2": 8}])


# ---------------------------------------------------------------------------
# Snapshots + service
# ---------------------------------------------------------------------------


def test_snapshots_are_idempotent(repo: MarketDataRepository) -> None:
    repo.write_snapshots(AS_OF, [_snapshot("AAA.IS", close=99.0)])
    rows = repo.get_snapshots(AS_OF)
    assert len(rows) == 1 and rows[0]["close"] == 99.0


def test_catalog_reports_counts_and_descriptions(repo: MarketDataRepository) -> None:
    catalog = ScreenerService(repo).catalog()
    assert catalog["as_of"] == AS_OF.isoformat()
    rsi = next(item for item in catalog["screens"] if item["code"] == "rsi_dip")
    assert rsi["count"] == 3
    assert rsi["description"]


def test_screen_rows_join_scan_hits_and_metrics(repo: MarketDataRepository) -> None:
    payload = ScreenerService(repo).screen_rows("rsi_dip")
    assert payload["total"] == 3
    codes = [row["code"] for row in payload["rows"]]
    assert codes == ["AAA", "BBB", "CCC"] or set(codes) == {"AAA", "BBB", "CCC"}
    assert payload["rows"][0]["scan_value"] is not None
    assert payload["rows"][0]["metrics"]["rsi14"] is not None


def test_query_filters_by_condition_and_sector(repo: MarketDataRepository) -> None:
    service = ScreenerService(repo)
    conditions = parse_conditions([{"field": "pe_ttm", "op": "<=", "value": 7}])
    payload = service.query(conditions=conditions)
    assert payload["total"] == 3  # PE 5, 6, 7

    sector = service.query(sector="Teknoloji")
    assert sector["total"] == 4  # AAA, CCC, EEE, GGG


def test_query_sorts_desc_and_keeps_nulls_last(repo: MarketDataRepository) -> None:
    repo.write_snapshots(
        AS_OF,
        [
            _snapshot(f"{code}.IS", rsi14=None if code == "AAA" else 40.0 + i)
            for i, code in enumerate(CODES)
        ],
    )
    payload = ScreenerService(repo).query(sort="rsi14", order="desc")
    values = [row["metrics"]["rsi14"] for row in payload["rows"]]
    assert values[-1] is None
    assert values[:-1] == sorted(values[:-1], reverse=True)


def test_query_rejects_unknown_sort(repo: MarketDataRepository) -> None:
    with pytest.raises(ScreenerError):
        ScreenerService(repo).query(sort="; drop table users")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "screener_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-screener-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        STOCK_PAGES_PUBLIC=False,
        SCREENER_FREE_LIMIT=5,
        SCREEN_SCANS_ENABLED=False,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        repository = MarketDataRepository(manager)
        repository.upsert_instruments(
            [Instrument(code=code, ticker=f"{code}.IS", name=code, sector="Test") for code in CODES]
        )
        repository.write_snapshots(
            AS_OF, [_snapshot(f"{code}.IS", close=10.0 + i) for i, code in enumerate(CODES)]
        )
        repository.replace_scan_results(
            "rsi_dip", AS_OF, [(f"{code}.IS", 20.0, "RSI") for code in CODES]
        )
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


def test_member_cannot_open_screener_when_private(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client)
        assert client.get("/ui/screener").status_code == 302
        resp = client.get("/api/screens", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


def test_admin_gets_catalog_and_rows(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin@bistbot.local")
        _promote(app, "admin@bistbot.local")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/ui/screener").status_code == 200
        catalog = client.get("/api/screens", headers=headers)
        assert catalog.status_code == 200
        assert catalog.get_json()["screens"][0]["code"] == "rsi_dip"
        rows = client.get("/api/screens/rsi_dip", headers=headers)
        assert rows.status_code == 200
        assert rows.get_json()["total"] == len(CODES)
        assert rows.get_json()["truncated"] is False


def test_member_sees_only_free_rows_when_public(app: Flask) -> None:
    with settings.override(STOCK_PAGES_PUBLIC=True, SCREENER_FREE_LIMIT=3):
        with app.test_client() as client:
            token = _login(client, "free@bistbot.local")
            resp = client.get("/api/screens/rsi_dip", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            body = resp.get_json()
            assert len(body["rows"]) == 3
            assert body["truncated"] is True
            assert body["total"] == len(CODES)


def test_query_endpoint_validates_and_returns_rows(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin2@bistbot.local")
        _promote(app, "admin2@bistbot.local")
        headers = {"Authorization": f"Bearer {token}"}
        ok = client.post(
            "/api/screener/query",
            headers=headers,
            json={"conditions": [{"field": "pe_ttm", "op": "<=", "value": 8}]},
        )
        assert ok.status_code == 200
        assert ok.get_json()["total"] == len(CODES)  # every seeded row has PE 8.0

        bad = client.post(
            "/api/screener/query",
            headers=headers,
            json={"conditions": [{"field": "close; drop", "op": "<", "value": 1}]},
        )
        assert bad.status_code == 400
        assert "Bilinmeyen alan" in bad.get_json()["message"]


def test_screener_pages_have_no_advice_language() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "bist_bot"
    for path in (root / "templates" / "stitch" / "screener.html", root / "static" / "screener.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(AL|SAT)\b", text), path.name
        assert "Stop-Loss" not in text, path.name
        assert "Hedef:" not in text, path.name
