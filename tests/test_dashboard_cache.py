"""Dashboard cache and force-refresh tests."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

import pandas as pd
from flask_jwt_extended import create_access_token
from sqlalchemy import text

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dashboard import create_dashboard_app  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.execution.base import OrderResult, OrderState  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


class FetcherSpy:
    def __init__(self, scan_payload: dict[str, dict[str, Any]] | None = None) -> None:
        self.clear_calls: list[tuple[str, str | None]] = []
        self.scan_force_refresh: list[bool] = []
        self.fetch_single_force: list[bool] = []
        self.analysis_cache: dict[str, dict[str, Any]] = {}
        self.scan_payload = scan_payload or {}

    def clear_cache(
        self,
        scope: str = "all",
        ticker: str | None = None,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        _ = period, interval
        self.clear_calls.append((scope, ticker))

    def fetch_all(self, period: str = "3mo", interval: str = "1d", force: bool = False):
        _ = period, interval, force
        return {}

    def fetch_multi_timeframe_all(
        self,
        trend_period: str = "6mo",
        trend_interval: str = "1d",
        trigger_period: str = "1mo",
        trigger_interval: str = "15m",
        force_refresh: bool = False,
        limit: int | None = None,
    ):
        _ = trend_period, trend_interval, trigger_period, trigger_interval, limit
        self.scan_force_refresh.append(force_refresh)
        return self.scan_payload

    def fetch_single(
        self,
        ticker: str,
        period: str = "6mo",
        interval: str = "1d",
        force: bool = False,
    ):
        _ = ticker, period, interval
        self.fetch_single_force.append(force)
        return pd.DataFrame(
            {
                "open": [float(i) for i in range(1, 81)],
                "high": [float(i) + 1 for i in range(1, 81)],
                "low": [float(i) - 0.5 for i in range(1, 81)],
                "close": [float(i) + 0.2 for i in range(1, 81)],
                "volume": [100 + i for i in range(80)],
            },
            index=pd.date_range("2025-01-01", periods=80),
        )

    def get_cached_analysis(self, cache_key: str, force: bool = False) -> Any | None:
        if force:
            return None
        return self.analysis_cache.get(cache_key)

    def store_analysis(self, cache_key: str, value: Any) -> None:
        self.analysis_cache[cache_key] = dict(value)


class EngineSpy:
    def __init__(self, scan_signals: list[Signal] | None = None) -> None:
        self.analyze_calls = 0
        self.scan_signals = scan_signals or []

    def scan_all(self, data):
        _ = data
        return list(self.scan_signals)

    def get_actionable_signals(self, signals):
        return signals

    def analyze(self, ticker: str, df, enforce_sector_limit: bool = False):
        _ = df, enforce_sector_limit
        self.analyze_calls += 1
        return Signal(ticker=ticker, signal_type=SignalType.BUY, score=25, price=5.2)


class BrokerSpy:
    def __init__(self) -> None:
        self.authenticate_calls = 0
        self.order_calls = 0

    def authenticate(self) -> bool:
        self.authenticate_calls += 1
        return True

    def place_order(self, ticker, side, quantity, order_type, price=None, stop_price=None):
        _ = ticker, side, quantity, order_type, price, stop_price
        self.order_calls += 1
        return OrderResult(accepted=True, order_id="ord-1", broker_order_id="brk-1", state=OrderState.SENT)


def _build_authorized_client(
    tmp_path,
    *,
    scan_signals: list[Signal] | None = None,
    scan_payload: dict[str, dict[str, Any]] | None = None,
    broker: Any | None = None,
    **overrides: Any,
):
    fetcher = FetcherSpy(scan_payload=scan_payload)
    engine = EngineSpy(scan_signals=scan_signals)
    with settings.override(
        DB_PATH=str(tmp_path / "dashboard_cache.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
        **overrides,
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "dashboard_cache.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, fetcher), cast(Any, engine), db, broker=broker)
        app.config["TESTING"] = True
        with app.app_context():
            token = create_access_token(identity="admin@bistbot.local")
        client = app.test_client()
    return client, fetcher, engine, token, db


def test_scan_endpoint_accepts_force_refresh(tmp_path):
    client, fetcher, _engine, token, _db = _build_authorized_client(tmp_path)

    response = client.post(
        "/api/scan",
        json={"force_refresh": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["force_refresh"] is True
    assert fetcher.scan_force_refresh == [True]
    assert ("intraday_fetch", None) in fetcher.clear_calls
    assert ("analysis", None) in fetcher.clear_calls


def test_analyze_endpoint_uses_analysis_cache_and_force_refresh(tmp_path):
    client, fetcher, engine, token, _db = _build_authorized_client(tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.get("/api/analyze/THYAO", headers=headers)
    second = client.get("/api/analyze/THYAO", headers=headers)
    forced = client.get("/api/analyze/THYAO?force_refresh=true", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert forced.status_code == 200
    assert engine.analyze_calls == 2
    assert fetcher.fetch_single_force == [False, True]
    assert ("analysis", "THYAO.IS") in fetcher.clear_calls
    assert second.get_json()["force_refresh"] is False
    assert forced.get_json()["force_refresh"] is True


def test_scan_endpoint_reuses_scan_service_side_effects(tmp_path):
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=5.2)
    client, _fetcher, _engine, token, db = _build_authorized_client(
        tmp_path,
        scan_signals=[signal],
        scan_payload={"THYAO.IS": {"trend": object(), "trigger": object()}},
    )

    with settings.override(PAPER_MODE=True):
        response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert len(payload["signals"]) == 1
    with db.manager.engine.begin() as conn:
        trade_count = conn.execute(text("SELECT COUNT(*) FROM paper_trades")).scalar_one()
    assert trade_count == 1


def test_scan_endpoint_auto_executes_when_broker_is_available(tmp_path):
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=75,
        price=5.2,
        position_size=10,
    )
    broker = BrokerSpy()
    client, _fetcher, _engine, token, db = _build_authorized_client(
        tmp_path,
        scan_signals=[signal],
        scan_payload={"THYAO.IS": {"trend": object(), "trigger": object()}},
        broker=broker,
    )

    with settings.override(AUTO_EXECUTE=True):
        response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert broker.authenticate_calls == 1
    assert broker.order_calls == 1
    pending_orders = db.get_pending_orders()
    assert len(pending_orders) == 1
    assert pending_orders[0]["state"] == "SENT"
