"""Faz 6: link tokens, message handling, digest building and API guards."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask
from flask.testing import FlaskClient

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.alert_repository import AlertRepository
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.db.repositories.user_portfolio_repository import UserPortfolioRepository
from bist_bot.services.alert_digest_service import AlertDigestService
from bist_bot.services.telegram_link_service import TelegramLinkService, hash_token

AS_OF = date(2026, 10, 21)
PREV = date(2026, 10, 20)


def _make_user(manager: DatabaseManager, email: str = "u1@example.com") -> int:
    with manager.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO users (email, password_hash, role, created_at, updated_at) "
                "VALUES (:email, 'x', 'admin', :now, :now)"
            ),
            {"email": email, "now": datetime.now(UTC)},
        )
        return int(
            conn.execute(sa.text("SELECT id FROM users WHERE email=:e"), {"e": email}).scalar()
        )


@pytest.fixture
def env(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "alerts.db"))
    manager.initialize()
    market = MarketDataRepository(manager)
    alerts = AlertRepository(manager)
    users = UserPortfolioRepository(manager)
    market.upsert_instruments(
        [
            Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Test"),
            Instrument(code="BBB", ticker="BBB.IS", name="B", sector="Test"),
        ]
    )
    for ticker in ("AAA.IS", "BBB.IS"):
        market.write_bars(
            ticker,
            [
                DailyBar(date=PREV, close=10.0, close_raw=10.0),
                DailyBar(date=AS_OF, close=11.0, close_raw=11.0),
            ],
            source="isyatirim",
        )
    market.replace_scan_results("rsi_dip", PREV, [("AAA.IS", 25.0, "RSI")])
    market.replace_scan_results(
        "rsi_dip", AS_OF, [("AAA.IS", 24.0, "RSI"), ("BBB.IS", 22.0, "RSI")]
    )
    market.write_snapshots(
        AS_OF,
        [
            {"ticker": "AAA.IS", "close": 11.0, "change_pct": 10.0},
            {"ticker": "BBB.IS", "close": 11.0, "change_pct": 10.0},
        ],
    )
    market.write_snapshots(
        PREV,
        [
            {"ticker": "AAA.IS", "close": 10.0, "change_pct": 1.0},
            {"ticker": "BBB.IS", "close": 10.0, "change_pct": 1.0},
        ],
    )
    user_id = _make_user(manager)
    return manager, market, alerts, users, user_id


class _NullNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_to_chat(self, chat_id: str, text: str) -> bool:
        self.sent.append((chat_id, text))
        return True


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------


def test_link_token_is_single_use_and_hashed(env) -> None:
    manager, _market, alerts, _users, user_id = env
    service = TelegramLinkService(alerts, None, settings)

    with settings.override(TELEGRAM_USER_BOT_USERNAME="@testbot"):
        token = service.create_token(user_id)
    assert token is not None and "?start=" in token["url"]
    raw = token["url"].split("?start=")[1]

    with manager.engine.connect() as conn:
        stored = conn.execute(sa.text("SELECT token_hash FROM user_telegram_link_tokens")).scalar()
    assert stored == hash_token(raw)
    assert stored != raw

    reply = service.handle_message({"chat": {"id": 42, "type": "private"}, "text": f"/start {raw}"})
    assert "kuruldu" in reply
    assert alerts.get_link(user_id)["chat_id"] == "42"

    again = service.handle_message({"chat": {"id": 43, "type": "private"}, "text": f"/start {raw}"})
    assert "geçersiz" in again


def test_group_chats_are_rejected(env) -> None:
    _manager, _market, alerts, _users, user_id = env
    service = TelegramLinkService(alerts, None, settings)
    with settings.override(TELEGRAM_USER_BOT_USERNAME="@testbot"):
        token = service.create_token(user_id)
    raw = token["url"].split("?start=")[1]
    reply = service.handle_message({"chat": {"id": -5, "type": "group"}, "text": f"/start {raw}"})
    assert "özel sohbet" in reply
    assert alerts.get_link(user_id) is None


def test_expired_token_is_rejected(env) -> None:
    _manager, _market, alerts, _users, user_id = env
    service = TelegramLinkService(alerts, None, settings)
    alerts.create_link_token(user_id, hash_token("abc"), datetime.now(UTC) - timedelta(minutes=1))
    reply = service.handle_message({"chat": {"id": 1, "type": "private"}, "text": "/start abc"})
    assert "geçersiz" in reply


def test_stop_removes_the_link(env) -> None:
    _manager, _market, alerts, _users, user_id = env
    alerts.save_link(user_id, "42", "user")
    service = TelegramLinkService(alerts, None, settings)
    service.handle_message({"chat": {"id": 42, "type": "private"}, "text": "/stop"})
    assert alerts.get_link(user_id) is None


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def _digest(market, alerts, users, notifier=None) -> AlertDigestService:
    return AlertDigestService(alerts, market, users, notifier, settings)


def test_screen_alert_reports_only_new_entrants(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    alerts.add_alert(user_id, {"kind": "screen", "target": "rsi_dip"})

    result = _digest(market, alerts, users).build(user_id, AS_OF)
    assert result.message is not None
    assert "BBB" in result.message
    # AAA was already in yesterday's scan, so it is not announced again.
    assert "AAA" not in result.message


def test_watchlist_only_filter(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    watchlist_id = users.create_watchlist(user_id, "Takip")
    users.add_watchlist_item(user_id, watchlist_id, "AAA.IS")
    alerts.add_alert(user_id, {"kind": "screen", "target": "rsi_dip", "only_watchlist": True})

    result = _digest(market, alerts, users).build(user_id, AS_OF)
    assert result.empty, "AAA is old, BBB is not in the watchlist"


def test_price_alert_fires_once_and_disables(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    alert_id = alerts.add_alert(
        user_id, {"kind": "price", "target": "AAA.IS", "op": "above", "threshold": 10.5}
    )
    service = _digest(market, alerts, users)

    first = service.build(user_id, AS_OF)
    assert first.message is not None and "AAA" in first.message
    stored = next(a for a in alerts.list_alerts(user_id) if a["id"] == alert_id)
    assert stored["enabled"] is False


def test_empty_digest_is_not_sent(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    alerts.add_alert(
        user_id, {"kind": "price", "target": "AAA.IS", "op": "above", "threshold": 99.0}
    )
    notifier = _NullNotifier()
    results = _digest(market, alerts, users, notifier).run(as_of=AS_OF)
    assert notifier.sent == []
    assert results and results[0].empty


def test_digest_is_idempotent_per_day(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    alerts.add_alert(user_id, {"kind": "change", "target": "AAA.IS", "threshold": 5})
    notifier = _NullNotifier()
    service = _digest(market, alerts, users, notifier)

    service.run(as_of=AS_OF)
    service.run(as_of=AS_OF)
    assert len(notifier.sent) == 1
    assert alerts.was_digest_sent(user_id, AS_OF)


def test_preview_does_not_mark_as_sent(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    alerts.add_alert(user_id, {"kind": "change", "target": "AAA.IS", "threshold": 5})
    service = _digest(market, alerts, users)

    service.run(as_of=AS_OF, send=False)
    assert not alerts.was_digest_sent(user_id, AS_OF)


def test_digest_escapes_and_stays_short(env) -> None:
    _manager, market, alerts, users, user_id = env
    alerts.save_link(user_id, "42", None)
    alerts.add_alert(user_id, {"kind": "change", "target": "AAA.IS", "threshold": 1})
    result = _digest(market, alerts, users).build(user_id, AS_OF)
    assert result.message is not None
    assert len(result.message) <= 3900
    assert "<script" not in result.message


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "alerts_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-alerts-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        STOCK_PAGES_PUBLIC=False,
        TELEGRAM_USER_BOT_USERNAME="@testbot",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        market = MarketDataRepository(manager)
        market.upsert_instruments(
            [Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Test")]
        )
        market.write_bars(
            "AAA.IS", [DailyBar(date=AS_OF, close=11.0, close_raw=11.0)], source="isyatirim"
        )
        market.write_snapshots(AS_OF, [{"ticker": "AAA.IS", "close": 11.0, "change_pct": 10.0}])
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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_member_cannot_open_alerts_when_private(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client)
        assert client.get("/ui/alerts").status_code == 302
        assert client.get("/api/alerts", headers=_headers(token)).status_code == 403


def test_admin_alert_flow(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin@bistbot.local")
        _promote(app, "admin@bistbot.local")
        headers = _headers(token)

        assert client.get("/ui/alerts").status_code == 200
        created = client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "price", "target": "AAA", "op": "above", "threshold": 10},
        )
        assert created.status_code == 201
        listed = client.get("/api/alerts", headers=headers).get_json()["alerts"]
        assert listed[0]["target"] == "AAA.IS"

        preview = client.get("/api/alerts/preview?as_of=2026-10-21", headers=headers)
        assert preview.status_code == 200
        assert "AAA" in (preview.get_json()["message"] or "")

        link = client.post("/api/alerts/telegram/link", headers=headers)
        assert link.status_code == 200 and "?start=" in link.get_json()["url"]

        saved = client.post(
            "/api/saved-screens",
            headers=headers,
            json={
                "name": "Ucuzlar",
                "payload": {"conditions": [{"field": "pe_ttm", "op": "<=", "value": 10}]},
            },
        )
        assert saved.status_code == 201


def test_alert_validation(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin2@bistbot.local")
        _promote(app, "admin2@bistbot.local")
        headers = _headers(token)
        bad = client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "price", "target": "AAA", "op": "up", "threshold": 1},
        )
        assert bad.status_code == 400
        unknown = client.post(
            "/api/alerts",
            headers=headers,
            json={"kind": "price", "target": "NOPE", "op": "above", "threshold": 1},
        )
        assert unknown.status_code == 404
        bad_screen = client.post(
            "/api/saved-screens",
            headers=headers,
            json={
                "name": "x",
                "payload": {"conditions": [{"field": "x; drop", "op": "<", "value": 1}]},
            },
        )
        assert bad_screen.status_code == 400


def test_alerts_pages_have_no_advice_language() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "bist_bot"
    for name in ("alerts.html",):
        text = (root / "templates" / "stitch" / name).read_text(encoding="utf-8")
        assert not re.search(r"\b(AL|SAT)\b", text), name
        assert "Stop-Loss" not in text, name
        assert "Hedef:" not in text, name
