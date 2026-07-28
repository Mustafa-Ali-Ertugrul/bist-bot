"""System-level integration tests for API, persistence, and orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pandas as pd
from dashboard import create_dashboard_app
from flask_jwt_extended import create_access_token
from sqlalchemy import text

from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.execution.base import OrderResult, OrderState
from bist_bot.scanner import ScanService
from bist_bot.services.execution_service import ExecutionService
from bist_bot.strategy.signal_models import Signal, SignalType


def _history_frame(periods: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [float(i) for i in range(1, periods + 1)],
            "high": [float(i) + 1.0 for i in range(1, periods + 1)],
            "low": [float(i) - 0.5 for i in range(1, periods + 1)],
            "close": [float(i) + 0.2 for i in range(1, periods + 1)],
            "volume": [1000 + i for i in range(periods)],
        },
        index=pd.date_range("2025-01-01", periods=periods),
    )


class ApiFetcherStub:
    def __init__(
        self,
        *,
        scan_payload: dict[str, dict[str, pd.DataFrame]] | None = None,
        analyze_df: pd.DataFrame | None = None,
    ) -> None:
        self.scan_payload = scan_payload if scan_payload is not None else {}
        self.analyze_df = analyze_df if analyze_df is not None else _history_frame()
        self.scan_calls = 0
        self.analyze_calls = 0

    def clear_cache(
        self,
        scope: str = "all",
        ticker: str | None = None,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        _ = scope, ticker, period, interval

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
    ) -> dict[str, dict[str, pd.DataFrame]]:
        _ = trend_period, trend_interval, trigger_period, trigger_interval, force_refresh
        self.scan_calls += 1
        return self.scan_payload

    def fetch_single(
        self,
        ticker: str,
        period: str = "6mo",
        interval: str = "1d",
        force: bool = False,
    ) -> pd.DataFrame | None:
        _ = ticker, period, interval, force
        self.analyze_calls += 1
        return self.analyze_df

    def get_cached_analysis(self, cache_key: str, force: bool = False) -> Any | None:
        _ = cache_key, force
        return None

    def store_analysis(self, cache_key: str, value: Any) -> None:
        _ = cache_key, value


class ApiEngineStub:
    def __init__(
        self, scan_signals: list[Signal] | None = None, analyze_signal: Signal | None = None
    ) -> None:
        self.scan_signals = scan_signals or []
        self.analyze_signal = analyze_signal

    def scan_all(self, data):
        _ = data
        return list(self.scan_signals)

    def get_actionable_signals(self, signals):
        return [signal for signal in signals if signal.signal_type is not SignalType.HOLD]

    def analyze(self, ticker: str, df, enforce_sector_limit: bool = False):
        _ = ticker, df, enforce_sector_limit
        return self.analyze_signal


class RaisingScanFetcher(ApiFetcherStub):
    def fetch_multi_timeframe_all(self, *args, **kwargs):
        raise RuntimeError("scan provider unavailable")


class RaisingAnalyzeEngine(ApiEngineStub):
    def analyze(self, ticker: str, df, enforce_sector_limit: bool = False):
        _ = ticker, df, enforce_sector_limit
        raise RuntimeError("indicator calculation failed")


class BrokerStub:
    def __init__(self, *, should_raise: bool = False) -> None:
        self.should_raise = should_raise
        self.orders: list[dict[str, Any]] = []

    def authenticate(self) -> bool:
        return True

    def place_order(self, ticker, side, quantity, order_type, price=None, stop_price=None):
        self.orders.append(
            {
                "ticker": ticker,
                "side": side.value,
                "quantity": quantity,
                "order_type": order_type.value,
                "price": price,
                "stop_price": stop_price,
            }
        )
        if self.should_raise:
            raise RuntimeError("broker rejected order")
        return OrderResult(
            accepted=True,
            order_id="ORD-1",
            broker_order_id="BRK-1",
            state=OrderState.SENT,
        )


def _build_client(tmp_path, fetcher, engine):
    with settings.override(
        DB_PATH=str(tmp_path / "integration_api.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "integration_api.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, fetcher), cast(Any, engine), db)
        app.config["TESTING"] = True
        with app.app_context():
            token = create_access_token(identity="admin@bistbot.local")
        return app.test_client(), db, manager, token


def test_api_scan_persists_actionable_signals_and_logs(tmp_path) -> None:
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=72.0,
        price=101.5,
        stop_loss=95.0,
        target_price=115.0,
        position_size=8,
        reasons=["Momentum"],
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )
    fetcher = ApiFetcherStub(
        scan_payload={"THYAO.IS": {"trend": _history_frame(), "trigger": _history_frame()}}
    )
    engine = ApiEngineStub(scan_signals=[signal])
    client, db, manager, token = _build_client(tmp_path, fetcher, engine)

    response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scanned"] == 1
    assert len(payload["signals"]) == 1
    assert db.get_latest_signal("THYAO.IS") is not None
    with manager.engine.begin() as conn:
        scan_log_count = conn.execute(text("SELECT COUNT(*) FROM scan_log")).scalar_one()
    assert scan_log_count == 1


def test_api_scan_returns_500_when_fetch_fails(tmp_path) -> None:
    client, _db, _manager, token = _build_client(tmp_path, RaisingScanFetcher(), ApiEngineStub())

    response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 500
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "error"
    assert "scan provider unavailable" in payload["message"]


def test_api_analyze_returns_signal_payload(tmp_path) -> None:
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=28.0,
        price=80.0,
        stop_loss=75.0,
        target_price=92.0,
        reasons=["Trend"],
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )
    client, _db, _manager, token = _build_client(
        tmp_path, ApiFetcherStub(), ApiEngineStub(analyze_signal=signal)
    )

    response = client.get("/api/analyze/THYAO", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ticker"] == "THYAO.IS"
    assert payload["signal"]["type"] == SignalType.BUY.value
    assert len(payload["price_data"]) == 60


def test_api_analyze_uses_batch_fallback_when_single_fetch_fails(tmp_path) -> None:
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=28.0,
        price=80.0,
        stop_loss=75.0,
        target_price=92.0,
        reasons=["Trend"],
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )

    class ProviderStub:
        def __init__(self) -> None:
            self.history_calls: list[str] = []
            self.batch_calls: list[list[str]] = []

        def fetch_history(self, ticker: str, period: str, interval: str):
            _ = period, interval
            self.history_calls.append(ticker)
            raise RuntimeError("single fetch failed")

        def fetch_batch(self, tickers: list[str], period: str, interval: str):
            _ = period, interval
            self.batch_calls.append(list(tickers))
            return {tickers[0]: _history_frame()}

        def fetch_quote(self, ticker: str):
            _ = ticker
            return None

        def fetch_universe(self, force_refresh: bool = False):
            _ = force_refresh
            return ["THYAO.IS", "ASELS.IS", "EREGL.IS"]

    fetcher = BISTDataFetcher(
        watchlist=["THYAO.IS", "ASELS.IS", "EREGL.IS"], provider=ProviderStub()
    )
    client, _db, _manager, token = _build_client(
        tmp_path, fetcher, ApiEngineStub(analyze_signal=signal)
    )

    response = client.get("/api/analyze/THYAO", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ticker"] == "THYAO.IS"
    assert payload["signal"]["type"] == SignalType.BUY.value
    assert fetcher.provider.history_calls == ["THYAO.IS"]
    assert fetcher.provider.batch_calls == [["THYAO.IS"]]
    assert fetcher.get_last_history_fetch_meta("THYAO.IS", "6mo", "1d") == {
        "source": "batch_fallback",
        "status": "success",
        "reason": "single_exception",
    }


def test_api_analyze_returns_500_when_engine_fails(tmp_path) -> None:
    client, _db, _manager, token = _build_client(tmp_path, ApiFetcherStub(), RaisingAnalyzeEngine())

    response = client.get("/api/analyze/THYAO", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 500
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "error"
    assert "indicator calculation failed" in payload["message"]


def test_signal_and_order_persistence_integration(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "integration_repo.db"))
    db = DataAccess(manager)
    signal = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.BUY,
        score=32.0,
        price=55.5,
        stop_loss=52.0,
        target_price=63.0,
        position_size=12,
        reasons=["Volume", "Breakout"],
        timestamp=datetime(2025, 1, 2, 11, 0, 0),
    )

    db.save_signal(signal)
    created = db.create_order(
        ticker="ASELS.IS",
        side="BUY",
        quantity=12,
        order_type="MARKET",
        price=None,
        state="CREATED",
    )
    updated = db.update_order(
        created["id"], state="FILLED", broker_order_id="BRK-9", filled_qty=12, avg_fill_price=56.0
    )

    latest_signal = db.get_latest_signal("ASELS.IS")
    stored_order = db.get_order(created["id"])

    assert latest_signal is not None
    assert latest_signal["reasons"] == ["Volume", "Breakout"]
    assert latest_signal["position_size"] == 12
    assert updated is not None
    assert stored_order is not None
    assert stored_order["state"] == "FILLED"
    assert stored_order["filled_qty"] == 12
    assert stored_order["avg_fill_price"] == 56.0


def test_scan_orchestration_auto_execute_creates_sent_order(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "integration_scan.db"))
    db = DataAccess(manager)
    broker = BrokerStub()
    execution_service = ExecutionService(
        db, broker=broker, settings=settings.replace(AUTO_EXECUTE=True)
    )
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80.0,
        price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        position_size=10,
        timestamp=datetime(2025, 1, 3, 10, 0, 0),
    )
    fetcher = ApiFetcherStub(
        scan_payload={"THYAO.IS": {"trend": _history_frame(), "trigger": _history_frame()}}
    )
    engine = ApiEngineStub(scan_signals=[signal])
    service = ScanService(
        fetcher,
        engine,
        notifier=cast(Any, object()),
        db=db,
        execution_service=execution_service,
        signal_change_service=cast(
            Any, type("NoopChange", (), {"check_signal_changes": lambda self, signals: None})()
        ),
        paper_trade_service=cast(
            Any,
            type(
                "NoopPaper",
                (),
                {
                    "queue_actionable_signals": lambda self, signals: None,
                    "update_open_trades": lambda self: None,
                },
            )(),
        ),
        notification_service=cast(
            Any,
            type(
                "NoopNotify",
                (),
                {"notify_scan_results": lambda self, signals, actionable, total: None},
            )(),
        ),
        settings=settings.replace(AUTO_EXECUTE=True, PAPER_MODE=False),
    )

    result = service.scan_once()

    assert result[0].ticker == "THYAO.IS"
    pending_orders = db.get_pending_orders()
    assert len(pending_orders) == 1
    assert pending_orders[0]["state"] == "SENT"
    assert broker.orders[0]["quantity"] == 10.0


def test_scan_orchestration_marks_order_rejected_when_broker_fails(tmp_path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "integration_scan_fail.db"))
    db = DataAccess(manager)
    broker = BrokerStub(should_raise=True)
    execution_service = ExecutionService(
        db, broker=broker, settings=settings.replace(AUTO_EXECUTE=True)
    )
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80.0,
        price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        position_size=10,
        timestamp=datetime(2025, 1, 3, 10, 0, 0),
    )
    fetcher = ApiFetcherStub(
        scan_payload={"THYAO.IS": {"trend": _history_frame(), "trigger": _history_frame()}}
    )
    engine = ApiEngineStub(scan_signals=[signal])
    service = ScanService(
        fetcher,
        engine,
        notifier=cast(Any, object()),
        db=db,
        execution_service=execution_service,
        signal_change_service=cast(
            Any, type("NoopChange", (), {"check_signal_changes": lambda self, signals: None})()
        ),
        paper_trade_service=cast(
            Any,
            type(
                "NoopPaper",
                (),
                {
                    "queue_actionable_signals": lambda self, signals: None,
                    "update_open_trades": lambda self: None,
                },
            )(),
        ),
        notification_service=cast(
            Any,
            type(
                "NoopNotify",
                (),
                {"notify_scan_results": lambda self, signals, actionable, total: None},
            )(),
        ),
        settings=settings.replace(AUTO_EXECUTE=True, PAPER_MODE=False),
    )

    service.scan_once()

    with manager.session_scope() as session:
        row = session.execute(
            text("SELECT state FROM orders ORDER BY id DESC LIMIT 1")
        ).scalar_one()
    assert row == "REJECTED"
