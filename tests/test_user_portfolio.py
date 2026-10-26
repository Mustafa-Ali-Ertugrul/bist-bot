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


def test_sell_then_rebuy_keeps_cash_and_invested_consistent(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, quantity=10, price=100)
    _buy(service, 1, pid, side="sell", trade_date="2026-01-05", quantity=10, price=110)

    sold = service.summary(1, pid)
    assert sold["totals"]["cash"] == pytest.approx(1100.0)
    assert sold["totals"]["net_invested"] == pytest.approx(1000.0)
    assert sold["totals"]["return_pct"] == pytest.approx(10.0)

    _buy(service, 1, pid, trade_date="2026-01-05", quantity=10, price=110)
    summary = service.summary(1, pid)
    totals = summary["totals"]
    assert totals["cash"] == pytest.approx(0.0)
    assert totals["net_invested"] == pytest.approx(1000.0)
    assert totals["value"] == pytest.approx(1200.0)
    assert totals["return_pct"] == pytest.approx(20.0)
    assert totals["realized"] == pytest.approx(100.0)


def test_benchmark_keeps_units_after_sale(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, quantity=10, price=100)
    _buy(service, 1, pid, side="sell", trade_date="2026-01-05", quantity=10, price=110)

    with settings.override(MONEY_MARKET_ANNUAL_RATE_PCT=0.0):
        summary = service.summary(1, pid)
    benchmark = summary["benchmark"]
    # Sale proceeds stay in the portfolio as cash: outside money is still 1000.
    assert benchmark["xu100_value"] == pytest.approx(1100.0)
    assert benchmark["money_market_value"] == pytest.approx(1000.0)
    assert summary["totals"]["value"] == pytest.approx(1100.0)
    assert benchmark["vs_xu100"] == pytest.approx(0.0)


def test_weekend_trade_shows_in_benchmark(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    # 2026-01-03 is a Saturday: priced off 01-02 and tracked by the benchmark.
    _buy(service, 1, pid, trade_date="2026-01-03", quantity=10, price=100)

    summary = service.summary(1, pid)
    assert summary["benchmark"]["portfolio_value"] == pytest.approx(1200.0)
    assert summary["benchmark"]["xu100_value"] == pytest.approx(1100.0)
    assert any(point["time"] == "2026-01-03" for point in summary["series"])


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


def test_backdated_sell_cannot_oversell(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    _buy(service, 1, pid, trade_date="2026-01-02", quantity=10, price=100)
    _buy(service, 1, pid, side="sell", trade_date="2026-01-05", quantity=10, price=110)

    with pytest.raises(TradeError):
        _buy(service, 1, pid, side="sell", trade_date="2026-01-03", quantity=5, price=105)


def test_delete_cannot_leave_oversold_ledger(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    buy_id = _buy(service, 1, pid, quantity=10, price=100)
    _buy(service, 1, pid, side="sell", trade_date="2026-01-05", quantity=10, price=110)

    with pytest.raises(TradeError):
        service.delete_transaction(1, pid, buy_id)
    assert service.summary(1, pid)["totals"]["cash"] == pytest.approx(1100.0)


def test_non_finite_trade_input_is_rejected(repos) -> None:
    _manager, market, user = repos
    service = _service(market, user)
    pid = _new_portfolio(user, 1)
    with pytest.raises(TradeError):
        _buy(service, 1, pid, quantity=float("nan"))
    with pytest.raises(TradeError):
        _buy(service, 1, pid, price=float("inf"))


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


def test_delete_transaction_endpoint_rejects_oversold_result(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "del@bistbot.local")
        _promote(app, "del@bistbot.local")
        headers = _headers(token)
        pid = client.post("/api/portfolios", headers=headers, json={"name": "P"}).get_json()["id"]
        buy = client.post(
            f"/api/portfolios/{pid}/transactions",
            headers=headers,
            json={
                "ticker": "THYAO",
                "side": "buy",
                "trade_date": "2026-01-02",
                "quantity": 10,
                "price": 100,
            },
        ).get_json()
        sold = client.post(
            f"/api/portfolios/{pid}/transactions",
            headers=headers,
            json={
                "ticker": "THYAO",
                "side": "sell",
                "trade_date": "2026-01-06",
                "quantity": 10,
                "price": 120,
            },
        ).get_json()
        rejected = client.delete(
            f"/api/portfolios/{pid}/transactions/{buy['id']}", headers=headers
        )
        assert rejected.status_code == 400
        assert client.get(f"/api/portfolios/{pid}", headers=headers).status_code == 200

        ok = client.delete(
            f"/api/portfolios/{pid}/transactions/{sold['id']}", headers=headers
        )
        assert ok.status_code == 200


def test_personal_pages_have_no_advice_language() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "bist_bot"
    for name in ("watchlist.html", "portfolio.html"):
        text = (root / "templates" / "stitch" / name).read_text(encoding="utf-8")
        assert not re.search(r"\b(AL|SAT)\b", text), name
        assert "Stop-Loss" not in text, name
        assert "Hedef:" not in text, name


def test_bulk_watchlist_items_and_quota(app: Flask) -> None:
    with settings.override(STOCK_PAGES_PUBLIC=True, FREE_WATCHLIST_ITEMS=2):
        with app.test_client() as client:
            token = _login(client, "bulk_wl@bistbot.local")
            headers = _headers(token)
            wl_id = client.post("/api/watchlists", headers=headers, json={"name": "Bulk"}).get_json()["id"]
            resp = client.post(
                f"/api/watchlists/{wl_id}/items/bulk",
                headers=headers,
                json={"tickers": ["THYAO", "THYAO", "NOPE"]},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["added"] == 1
            assert data["skipped"] == 1
            assert data["not_found"] == ["NOPE"]


def test_per_position_realized_pnl_edit_and_csv_import(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "p2_port@bistbot.local")
        _promote(app, "p2_port@bistbot.local")
        headers = _headers(token)
        pid = client.post("/api/portfolios", headers=headers, json={"name": "P2"}).get_json()["id"]

        # CSV dry-run preview
        csv_text = "trade_date,ticker,side,quantity,price,commission_tl\n2026-01-02,THYAO,buy,10,100,0\n2026-01-06,THYAO,sell,4,120,0\n"
        preview = client.post(
            f"/api/portfolios/{pid}/transactions/import",
            headers=headers,
            json={"csv": csv_text, "dry_run": True},
        )
        assert preview.status_code == 200
        assert preview.get_json()["valid"] is True
        assert preview.get_json()["imported"] == 0

        # Commit CSV import
        imported = client.post(
            f"/api/portfolios/{pid}/transactions/import",
            headers=headers,
            json={"csv": csv_text, "dry_run": False},
        )
        assert imported.status_code == 200
        assert imported.get_json()["imported"] == 2

        summary = client.get(f"/api/portfolios/{pid}", headers=headers).get_json()
        assert len(summary["positions"]) == 1
        assert summary["positions"][0]["quantity"] == pytest.approx(6.0)
        assert summary["positions"][0]["realized_pnl"] == pytest.approx(80.0)

        # Edit buy transaction to quantity=3 -> should fail because 4 were sold on 2026-01-06
        buy_tx_id = next(tx["id"] for tx in summary["transactions"] if tx["side"] == "buy")
        bad_edit = client.put(
            f"/api/portfolios/{pid}/transactions/{buy_tx_id}",
            headers=headers,
            json={
                "ticker": "THYAO",
                "side": "buy",
                "trade_date": "2026-01-02",
                "quantity": 3,
                "price": 100,
            },
        )
        assert bad_edit.status_code == 400

        # Valid edit: buy quantity=12
        ok_edit = client.put(
            f"/api/portfolios/{pid}/transactions/{buy_tx_id}",
            headers=headers,
            json={
                "ticker": "THYAO",
                "side": "buy",
                "trade_date": "2026-01-02",
                "quantity": 12,
                "price": 100,
            },
        )
        assert ok_edit.status_code == 200
        updated_summary = client.get(f"/api/portfolios/{pid}", headers=headers).get_json()
        assert updated_summary["positions"][0]["quantity"] == pytest.approx(8.0)
