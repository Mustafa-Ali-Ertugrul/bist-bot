"""Faz P4: accuracy, alert safety and scorecard honesty guards."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask
from sqlalchemy.exc import IntegrityError

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.alert_repository import (
    AlertRepository,
    _is_duplicate_violation,
)
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.db.repositories.user_portfolio_repository import UserPortfolioRepository
from bist_bot.scheduler import MarketScheduler
from bist_bot.services.alert_digest_service import AlertDigestService
from bist_bot.services.market_overview_service import MarketOverviewService
from bist_bot.services.scan_scorecard_service import ScanScorecardService
from bist_bot.services.stock_profile_service import (
    StockProfileService,
    fundamentals_stale,
    period_end_date,
)

TODAY = date.today()


def _bars(count: int, start: float = 100.0, step: float = 1.0) -> list[DailyBar]:
    out = []
    price = start
    for index in range(count):
        out.append(
            DailyBar(
                date=TODAY - timedelta(days=count - index),
                close=price,
                close_raw=price,
                market_cap_tl=price * 1_000_000,
                volume_tl=1_000_000.0,
            )
        )
        price += step
    return out


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "p4.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    repository.upsert_instruments(
        [
            Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Teknoloji"),
            Instrument(code="BBB", ticker="BBB.IS", name="B", sector="Sanayi"),
        ]
    )
    repository.write_bars("AAA.IS", _bars(400, 100.0, 1.0), source="isyatirim")
    repository.write_bars("BBB.IS", _bars(400, 80.0, 0.5), source="isyatirim")
    return repository


# ---------------------------------------------------------------------------
# P4.1 comparison accuracy
# ---------------------------------------------------------------------------


def test_short_chart_window_keeps_long_window_metrics(repo: MarketDataRepository) -> None:
    service = StockProfileService(repo)
    monthly = service.compare(["AAA", "BBB"], range_key="1m")
    yearly = service.compare(["AAA", "BBB"], range_key="1y")

    for short, long in zip(monthly["stocks"], yearly["stocks"], strict=True):
        assert short["series"], "1 aylık grafik boş olmamalı"
        # Chart window shrinks; the metrics behind it must not.
        assert short["returns"]["1y"] == long["returns"]["1y"]
        assert short["returns"]["1y"] is not None
        assert short["technical"]["high_52w"] == long["technical"]["high_52w"]
        assert short["technical"]["sma200"] == long["technical"]["sma200"]
        assert len(short["series"]) < len(long["series"])


def test_compare_series_starts_at_the_common_base_date(repo: MarketDataRepository) -> None:
    payload = StockProfileService(repo).compare(["AAA", "BBB"], range_key="1y")
    base = payload["base_date"]
    assert base
    for item in payload["stocks"]:
        assert item["series"][0]["time"] == base
        assert item["series"][0]["value"] == 100.0
        assert all(point["time"] >= base for point in item["series"])


def test_compare_flags_late_fundamentals(repo: MarketDataRepository) -> None:
    payload = StockProfileService(repo).compare(["AAA"], range_key="1y")
    fundamentals = payload["stocks"][0]["fundamentals"]
    assert "latest_period" in fundamentals
    assert isinstance(fundamentals["stale"], bool)


def test_period_end_and_staleness_helpers() -> None:
    assert period_end_date("2026/06") == date(2026, 6, 30)
    assert period_end_date("2026/12") == date(2026, 12, 31)
    assert period_end_date("bad") is None
    assert period_end_date(None) is None
    assert fundamentals_stale("2026/06", date(2026, 10, 1)) is False
    assert fundamentals_stale("2026/03", date(2026, 10, 1)) is True
    assert fundamentals_stale("2025/03", date(2026, 10, 1)) is True
    assert fundamentals_stale(None, date(2026, 10, 1)) is True


def test_historical_market_overview_uses_that_day_index(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "history.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    repository.upsert_instruments(
        [Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Teknoloji")]
    )
    older = date(2026, 10, 15)
    newer = date(2026, 10, 20)
    for day, change in ((older, 1.0), (newer, -2.0)):
        repository.write_snapshots(
            day,
            [
                {
                    "ticker": "AAA.IS",
                    "close": 10.0,
                    "change_pct": change,
                    "ret_1m": 0.0,
                    "avg_volume_20": 1000.0,
                    "market_cap_tl": 1_000_000.0,
                }
            ],
        )
    repository.write_benchmark_bars(
        "XU100",
        [
            (date(2026, 10, 14), 9000.0),
            (older, 9500.0),
            (date(2026, 10, 16), 9600.0),
            (newer, 9900.0),
        ],
        source="test",
    )

    service = MarketOverviewService(repository)
    historical = service.overview(as_of=older)
    latest = service.overview()

    assert historical["as_of"] == older.isoformat()
    assert historical["index"]["close"] == 9500.0
    assert historical["index"]["as_of"] == older.isoformat()
    assert latest["index"]["close"] == 9900.0


# ---------------------------------------------------------------------------
# P4.3 scorecard honesty
# ---------------------------------------------------------------------------


def test_scorecard_says_forward_returns_are_missing(repo: MarketDataRepository) -> None:
    repo.replace_scan_results("rsi_dip", TODAY, [("AAA.IS", 20.0, "RSI")])
    payload = ScanScorecardService(repo).scorecard("rsi_dip", horizons=(20,))

    assert payload is not None
    assert payload["hit_days"] == 1
    assert payload["hit_count"] == 1
    assert payload["horizons"][0]["observations"] == 0
    assert "ileri getiri" in payload["note"]


def test_scorecard_cache_reports_when_it_was_computed(repo: MarketDataRepository) -> None:
    service = ScanScorecardService(repo)
    service.all_scorecards(horizons=(20,))

    assert service.cache_hit is False
    meta = service.cache_metadata(horizons=(20,))
    assert meta["computed_at"]

    again = ScanScorecardService(repo)
    again.all_scorecards(horizons=(20,))
    assert again.cache_hit is True


def test_refresh_still_populates_the_cache(repo: MarketDataRepository) -> None:
    service = ScanScorecardService(repo)
    service.all_scorecards(horizons=(20,), use_cache=False)
    assert service.cache_hit is False
    assert repo.get_scorecard_cache("scorecards:all:20") is not None


def test_scorecard_cache_is_cleared_when_it_goes_stale(repo: MarketDataRepository) -> None:
    service = ScanScorecardService(repo)
    service.all_scorecards(horizons=(20,))
    assert repo.get_scorecard_cache("scorecards:all:20") is not None

    repo.clear_scorecard_cache()

    assert repo.get_scorecard_cache("scorecards:all:20") is None


# ---------------------------------------------------------------------------
# P4.4 alert safety
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "p4_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-p4-guards-123456",
        JWT_COOKIE_SECURE=False,
        RBAC_MODE="warn",
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
            [Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Teknoloji")]
        )
        market.write_bars("AAA.IS", _bars(60), source="isyatirim")
        market.write_snapshots(
            TODAY,
            [
                {
                    "ticker": "AAA.IS",
                    "close": 100.0,
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
            ],
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


def _headers(app: Flask, client, email: str) -> dict[str, Any]:
    client.post("/api/auth/register", json={"email": email, "password": "Str0ng-test-pass!"})
    token = client.post(
        "/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"}
    ).get_json()["access_token"]
    with app.config["_test_manager"].engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )
    return {"Authorization": f"Bearer {token}"}


def test_alert_patch_rejects_non_boolean_enabled(app: Flask) -> None:
    with app.test_client() as client:
        headers = _headers(app, client, "p4patch@bistbot.local")
        created = client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "price", "target": "AAA", "op": "above", "threshold": 5},
        )
        assert created.status_code == 201
        alert_id = created.get_json()["id"]

        bad = client.patch(f"/api/alerts/{alert_id}", headers=headers, json={"enabled": "false"})
        assert bad.status_code == 400

        good = client.patch(f"/api/alerts/{alert_id}", headers=headers, json={"enabled": False})
        assert good.status_code == 200
        assert good.get_json()["alert"]["enabled"] is False


def test_alert_patch_rejects_non_finite_threshold(app: Flask) -> None:
    with app.test_client() as client:
        headers = _headers(app, client, "p4threshold@bistbot.local")
        created = client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "price", "target": "AAA", "op": "above", "threshold": 5},
        )
        alert_id = created.get_json()["id"]

        for raw in ("NaN", "Infinity", "-1"):
            resp = client.patch(
                f"/api/alerts/{alert_id}", headers=headers, json={"threshold": raw}
            )
            assert resp.status_code == 400, raw


def test_alert_events_are_idempotent_per_day(app: Flask) -> None:
    with app.test_client() as client:
        headers = _headers(app, client, "p4events@bistbot.local")
        client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "price", "target": "AAA", "op": "above", "threshold": 0.01},
        )
        first = client.post("/api/alerts/events/refresh", headers=headers).get_json()
        second = client.post("/api/alerts/events/refresh", headers=headers).get_json()

        assert first["written"] >= 1
        assert second["written"] == 0
        listed = client.get("/api/alerts/events", headers=headers).get_json()
        refs = [(row["as_of"], row["ref"]) for row in listed["events"]]
        assert len(refs) == len(set(refs))


def test_alert_events_are_scoped_to_the_owner(app: Flask) -> None:
    with app.test_client() as client:
        first = _headers(app, client, "p4own1@bistbot.local")
        second = _headers(app, client, "p4own2@bistbot.local")
        client.post(
            "/api/alerts",
            headers=first,
            json={"kind": "price", "target": "AAA", "op": "above", "threshold": 0.01},
        )
        client.post("/api/alerts/events/refresh", headers=first)

        mine = client.get("/api/alerts/events", headers=second).get_json()
        assert mine["events"] == []
        assert mine["unread"] == 0

        other = client.get("/api/alerts/events", headers=first).get_json()
        event_id = other["events"][0]["id"]
        marked = client.post(
            "/api/alerts/events/read", headers=second, json={"id": event_id}
        ).get_json()
        assert marked["marked"] == 0


# ---------------------------------------------------------------------------
# P4.5 ordering: the digest must not consume an alert before its event exists
# ---------------------------------------------------------------------------


def _snapshot_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ticker": "AAA.IS",
        "close": 100.0,
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
def digest_setup(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "digest.db"))
    manager.initialize()
    market = MarketDataRepository(manager)
    market.upsert_instruments(
        [Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Teknoloji")]
    )
    market.write_bars("AAA.IS", _bars(60), source="isyatirim")
    market.write_snapshots(TODAY, [_snapshot_row()])
    now = datetime.now(UTC)
    with manager.engine.begin() as conn:
        user_id = conn.execute(
            sa.text(
                "INSERT INTO users (email, password_hash, role, created_at, updated_at) "
                "VALUES ('digest@bistbot.local', 'x', 'user', :n, :n) RETURNING id"
            ),
            {"n": now},
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO user_telegram_links (user_id, chat_id, linked_at) "
                "VALUES (:u, 'chat-1', :n)"
            ),
            {"u": user_id, "n": now},
        )
    alerts = AlertRepository(manager)
    alerts.add_alert(
        int(user_id),
        {"kind": "price", "target": "AAA.IS", "op": "above", "threshold": 1.0},
        limit=10,
    )
    return manager, market, alerts, int(user_id)


def test_digest_records_event_before_disabling_the_alert(digest_setup) -> None:
    _manager, market, alerts, user_id = digest_setup
    notifier = MagicMock()
    notifier.send_to_chat.return_value = True

    with settings.override(
        IN_APP_ALERT_EVENTS_ENABLED=True,
        USER_DIGEST_ENABLED=True,
        PUBLIC_BASE_URL="",
    ):
        service = AlertDigestService(
            alerts, market, UserPortfolioRepository(_manager), notifier, settings
        )
        results = service.run(as_of=TODAY, send=True)

    assert results and results[0].message
    assert notifier.send_to_chat.called

    assert alerts.list_alerts(user_id)[0]["enabled"] is False
    events = alerts.list_events(user_id)
    assert [event["kind"] for event in events] == ["alert"]
    assert events[0]["ref"].startswith("price:")
    assert "AAA" in events[0]["title"]


def test_scheduler_writes_inapp_events_before_the_digest() -> None:
    order: list[str] = []

    class FakeAlerts:
        def run_inapp_if_due(self, now):
            order.append("inapp")
            return True

        def run_if_due(self, now):
            order.append("digest")
            return True

    scheduler = MarketScheduler(MagicMock(), MagicMock(), alerts=FakeAlerts())
    scheduler._run_alerts(datetime.now(UTC))

    assert order == ["inapp", "digest"]


def test_duplicate_detection_only_matches_unique_violations() -> None:
    unique = IntegrityError(
        "INSERT", {}, Exception("UNIQUE constraint failed: user_alert_events.user_id")
    )
    not_null = IntegrityError(
        "INSERT", {}, Exception("NOT NULL constraint failed: user_alert_events.ref")
    )

    class FakePgError(Exception):
        sqlstate = "23505"

    assert _is_duplicate_violation(unique) is True
    assert _is_duplicate_violation(not_null) is False
    assert _is_duplicate_violation(IntegrityError("INSERT", {}, FakePgError("dup"))) is True
