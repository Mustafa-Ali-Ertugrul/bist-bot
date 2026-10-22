"""Faz 5: adjusted-unit portfolio maths, benchmarks, ownership and API."""

from __future__ import annotations

from datetime import date
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
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.db.repositories.user_portfolio_repository import (
    OwnershipError,
    UserPortfolioRepository,
)
from bist_bot.services.user_portfolio_service import TradeError, UserPortfolioService


def _bar(day: str, raw: float, adjusted: float) -> DailyBar:
    return DailyBar(date=date.fromisoformat(day), close=adjusted, close_raw=raw, volume_tl=1.0)


@pytest.fixture
def repos(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "portfolio.db"))
    manager.initialize()
    market = MarketDataRepository(manager)
    user = UserPortfolioRepository(manager)
    market.upsert_instruments(
        [
            Instrument(code="THYAO", ticker="THYAO.IS", name="THYAO", sector="Ulaşım"),
            Instrument(code="BONUS", ticker="BONUS.IS", name="Bonus", sector="Test"),
        ]
    )
    market.write_bars(
        "THYAO.IS",
        [
            _bar("2026-01-02", 100.0, 100.0),
            _bar("2026-01-05", 110.0, 110.0),
            _bar("2026-01-06", 120.0, 120.0),
        ],
        source="isyatirim",
    )
    # 5:1 bonus: pre-split raw is 5x adjusted; after the split raw == adjusted.
    market.write_bars(
        "BONUS.IS",
        [_bar("2026-05-11", 279.4, 55.88), _bar("2026-05-12", 50.0, 50.0)],
        source="isyatirim",
    )
    market.write_benchmark_bars(
        "XU100",
        [(date(2026, 1, 2), 1000.0), (date(2026, 1, 5), 1050.0), (date(2026, 1, 6), 1100.0)],
        source="isyatirim",
    )
    return manager, market, user


def _service(market, user) -> UserPortfolioService:
    return UserPortfolioService(user, market)


def _new_portfolio(user: UserPortfolioRepository, user_id: int) -> int:
    return user.create_portfolio(user_id, "Ana")


def _buy(service: UserPortfolioService, user_id: int, pid: int, **overrides: Any) -> int:
    payload = {
        "ticker": "THYAO",
        "side": "buy",
        "trade_date": "2026-01-02",
        "quantity": 10,
        "price": 100,
        "commission_tl": 0,
    }
    payload.update(overrides)
    return service.add_transaction(user_id, pid, payload)


# ---------------------------------------------------------------------------
# Maths
# ---------------------------------------------------------------------------


def test_plain_buy_values_at_latest_price(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid)

    summary = service.summary(1, pid)
    position = summary["positions"][0]
    assert position["quantity"] == pytest.approx(10)
    assert position["value"] == pytest.approx(1200.0)
    assert position["cost_basis"] == pytest.approx(1000.0)
    assert position["unrealized"] == pytest.approx(200.0)
    assert position["avg_cost"] == pytest.approx(100.0)
    assert summary["totals"]["value"] == pytest.approx(1200.0)


def test_bonus_issue_does_not_fake_a_loss(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, ticker="BONUS", trade_date="2026-05-11", quantity=10, price=279.4)

    summary = service.summary(1, pid)
    position = summary["positions"][0]
    # 10 shares became 50 after the 5:1 bonus; value tracks 50 x 50 TL.
    assert position["quantity"] == pytest.approx(50)
    assert position["value"] == pytest.approx(2500.0)
    assert position["unrealized_pct"] > -20, "a bonus issue must never show a ~80% fake loss"


def test_sell_after_bonus_and_oversell_guard(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, ticker="BONUS", trade_date="2026-05-11", quantity=10, price=279.4)

    _buy(
        service,
        1,
        pid,
        ticker="BONUS",
        side="sell",
        trade_date="2026-05-12",
        quantity=20,
        price=50,
    )
    summary = service.summary(1, pid)
    assert summary["positions"][0]["quantity"] == pytest.approx(30)

    with pytest.raises(TradeError):
        _buy(
            service,
            1,
            pid,
            ticker="BONUS",
            side="sell",
            trade_date="2026-05-12",
            quantity=60,
            price=50,
        )


def test_commission_and_realized_pnl(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, commission_tl=10)
    _buy(
        service,
        1,
        pid,
        side="sell",
        trade_date="2026-01-05",
        quantity=5,
        price=110,
        commission_tl=5,
    )
    summary = service.summary(1, pid)
    # Bought 1000 + 10 fee; sold 5 at 110 - 5 fee; remaining cost 505.
    assert summary["totals"]["realized"] == pytest.approx(550 - 5 - 505)
    assert summary["positions"][0]["quantity"] == pytest.approx(5)


def test_weekend_trade_uses_the_previous_session(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    # 2026-01-03 is a Saturday; price falls back to the 2nd.
    _buy(service, 1, pid, trade_date="2026-01-03")
    assert service.summary(1, pid)["positions"][0]["quantity"] == pytest.approx(10)


def test_benchmark_matches_cash_flow(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, quantity=10, price=100)

    with settings.override(MONEY_MARKET_ANNUAL_RATE_PCT=0.0):
        summary = service.summary(1, pid)
    benchmark = summary["benchmark"]
    assert benchmark["available"] is True
    assert benchmark["portfolio_value"] == pytest.approx(1200.0)
    # 1000 TL into XU100 at 1000 -> 1100 at 01-06.
    assert benchmark["xu100_value"] == pytest.approx(1100.0)
    assert benchmark["money_market_value"] == pytest.approx(1000.0)
    assert benchmark["vs_xu100"] == pytest.approx(9.09)


# ---------------------------------------------------------------------------
# Validation and ownership
# ---------------------------------------------------------------------------


def test_invalid_trades_are_rejected(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    with pytest.raises(TradeError):
        _buy(service, 1, pid, ticker="NOPE")
    with pytest.raises(TradeError):
        _buy(service, 1, pid, trade_date="2099-01-01")
    with pytest.raises(TradeError):
        _buy(service, 1, pid, quantity=0)
    with pytest.raises(TradeError):
        _buy(service, 1, pid, side="hold")


def test_other_users_records_are_not_visible(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)

    assert user.list_portfolios(2) == []
    with pytest.raises(OwnershipError):
        user.get_transactions(2, pid)
    with pytest.raises(OwnershipError):
        user.delete_portfolio(2, pid)
    with pytest.raises(OwnershipError):
        service.summary(2, pid)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "portfolio_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-portfolio-123456",
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
        market = MarketDataRepository(manager)
        market.upsert_instruments(
            [Instrument(code="THYAO", ticker="THYAO.IS", name="THYAO", sector="Ulaşım")]
        )
        market.write_bars(
            "THYAO.IS",
            [_bar("2026-01-02", 100.0, 100.0), _bar("2026-01-06", 120.0, 120.0)],
            source="isyatirim",
        )
        market.write_benchmark_bars(
            "XU100",
            [(date(2026, 1, 2), 1000.0), (date(2026, 1, 6), 1100.0)],
            source="isyatirim",
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


def test_member_cannot_use_personal_pages_when_private(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client)
        assert client.get("/ui/portfolio").status_code == 302
        assert client.get("/api/portfolios", headers=_headers(token)).status_code == 403


def test_admin_watchlist_and_portfolio_flow(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin@bistbot.local")
        _promote(app, "admin@bistbot.local")
        headers = _headers(token)

        assert client.get("/ui/watchlist").status_code == 200
        assert client.get("/ui/portfolio").status_code == 200

        watch = client.post("/api/watchlists", headers=headers, json={"name": "Takip"})
        assert watch.status_code == 201
        watch_id = watch.get_json()["id"]
        assert (
            client.post(
                f"/api/watchlists/{watch_id}/items", headers=headers, json={"ticker": "THYAO"}
            ).status_code
            == 200
        )
        lists = client.get("/api/watchlists", headers=headers).get_json()["watchlists"]
        assert lists[0]["rows"][0]["code"] == "THYAO"

        portfolio = client.post("/api/portfolios", headers=headers, json={"name": "Ana"})
        assert portfolio.status_code == 201
        pid = portfolio.get_json()["id"]
        trade = client.post(
            f"/api/portfolios/{pid}/transactions",
            headers=headers,
            json={
                "ticker": "THYAO",
                "side": "buy",
                "trade_date": "2026-01-02",
                "quantity": 10,
                "price": 100,
            },
        )
        assert trade.status_code == 201
        summary = client.get(f"/api/portfolios/{pid}", headers=headers).get_json()
        assert summary["totals"]["value"] == pytest.approx(1200.0)
        assert summary["benchmark"]["xu100_value"] == pytest.approx(1100.0)


def test_api_validation_errors(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin2@bistbot.local")
        _promote(app, "admin2@bistbot.local")
        headers = _headers(token)
        pid = client.post("/api/portfolios", headers=headers, json={"name": "P"}).get_json()["id"]

        bad_ticker = client.post(
            f"/api/portfolios/{pid}/transactions",
            headers=headers,
            json={
                "ticker": "NOPE",
                "side": "buy",
                "trade_date": "2026-01-02",
                "quantity": 1,
                "price": 1,
            },
        )
        assert bad_ticker.status_code == 400

        oversell = client.post(
            f"/api/portfolios/{pid}/transactions",
            headers=headers,
            json={
                "ticker": "THYAO",
                "side": "sell",
                "trade_date": "2026-01-06",
                "quantity": 1,
                "price": 120,
            },
        )
        assert oversell.status_code == 400

        unknown = client.get("/api/portfolios/999", headers=headers)
        assert unknown.status_code == 404


def test_personal_pages_have_no_advice_language() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "bist_bot"
    for name in ("watchlist.html", "portfolio.html"):
        text = (root / "templates" / "stitch" / name).read_text(encoding="utf-8")
        assert not re.search(r"\b(AL|SAT)\b", text), name
        assert "Stop-Loss" not in text, name
        assert "Hedef:" not in text, name
