"""Observability tests for metrics, structured logging, and alerts."""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any, cast
from unittest.mock import MagicMock

from flask_jwt_extended import create_access_token

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dashboard import create_dashboard_app  # noqa: E402

from bist_bot.app_logging import configure_logging, get_logger  # noqa: E402
from bist_bot.app_metrics import reset_metrics  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.observability.alerts import (  # noqa: E402
    Alert,
    AlertLevel,
    AlertManager,
    reset_alert_manager,
    send_alert,
)
from bist_bot.observability.logging import (  # noqa: E402
    log_event,
    log_order,
    log_risk_reject,
    log_signal,
)
from bist_bot.observability.metrics import (  # noqa: E402
    observe_order_latency,
    record_order,
    record_signal,
    render_observability_metrics,
    reset_observability_metrics,
    set_daily_pnl,
    set_positions_current,
)
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


class MetricsFetcher:
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
    ):
        _ = trend_period, trend_interval, trigger_period, trigger_interval, force_refresh
        return {"THYAO.IS": {"trend": object(), "trigger": object()}}

    def fetch_single(
        self, ticker: str, period: str = "6mo", interval: str = "1d", force: bool = False
    ):
        _ = ticker, period, interval, force
        return None

    def get_cached_analysis(self, cache_key: str, force: bool = False):
        _ = cache_key, force
        return None

    def store_analysis(self, cache_key: str, value: Any) -> None:
        _ = cache_key, value


class MetricsEngine:
    def scan_all(self, data):
        _ = data
        return [Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=10.0)]

    def get_actionable_signals(self, signals):
        return signals

    def analyze(self, ticker: str, df, enforce_sector_limit: bool = False):
        _ = ticker, df, enforce_sector_limit
        return None


def _build_client(tmp_path, fetcher: Any | None = None, engine: Any | None = None):
    reset_metrics()
    reset_observability_metrics()
    with settings.override(
        DB_PATH=str(tmp_path / "observability.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "observability.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(
            cast(Any, fetcher or MetricsFetcher()),
            cast(Any, engine or MetricsEngine()),
            db,
        )
        app.config["TESTING"] = True
        with app.app_context():
            token = create_access_token(identity="admin@bistbot.local")
        return app.test_client(), token


def _metric_value(metrics_text: str, name: str) -> float:
    for line in metrics_text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split()[1])
    raise AssertionError(f"Metric not found: {name}")


def test_metrics_endpoint_returns_200(tmp_path):
    client, token = _build_client(tmp_path)

    response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "bist_scan_total" in body
    assert "bist_bot_signals_total" in body
    assert "bist_bot_orders_total" in body
    assert "bist_bot_positions_current" in body
    assert "bist_bot_pnl_daily" in body
    assert "bist_bot_order_latency_seconds" in body


def test_metrics_endpoint_requires_auth(tmp_path):
    client, _token = _build_client(tmp_path)

    response = client.get("/metrics")

    assert response.status_code == 401


def test_scan_updates_metrics_counters(tmp_path):
    client, token = _build_client(tmp_path)

    scan_response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})
    metrics_response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})

    assert scan_response.status_code == 200
    metrics_text = metrics_response.get_data(as_text=True)
    assert _metric_value(metrics_text, "bist_scan_total") == 1.0
    assert _metric_value(metrics_text, "bist_signal_emitted_total") == 1.0
    assert _metric_value(metrics_text, "bist_last_scan_scanned_count") == 1.0
    assert 'bist_bot_signals_total{signal_type="BUY"}' in metrics_text


def test_scan_error_response_does_not_expose_exception_details(tmp_path):
    class FailingScanFetcher(MetricsFetcher):
        def fetch_multi_timeframe_all(self, *args, **kwargs):
            _ = args, kwargs
            raise RuntimeError("sensitive scan internals")

    client, token = _build_client(tmp_path, fetcher=FailingScanFetcher())

    response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 500
    body = response.get_json()
    assert body["status"] == "error"
    assert "message" in body
    # Must not leak exception internals; message may be localized or mapped.
    assert "sensitive scan internals" not in response.get_data(as_text=True)
    assert "RuntimeError" not in response.get_data(as_text=True)


def test_analyze_error_response_does_not_expose_exception_details(tmp_path):
    class FailingAnalyzeFetcher(MetricsFetcher):
        def fetch_single(self, *args, **kwargs):
            _ = args, kwargs
            raise RuntimeError("sensitive analyze internals")

    client, token = _build_client(tmp_path, fetcher=FailingAnalyzeFetcher())

    response = client.get("/api/analyze/THYAO", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 500
    body = response.get_json()
    assert body["status"] == "error"
    assert "message" in body
    assert "sensitive analyze internals" not in response.get_data(as_text=True)
    assert "RuntimeError" not in response.get_data(as_text=True)


def test_json_logging_renders_without_error():
    stream = io.StringIO()

    with settings.override(LOG_FORMAT="json", LOG_LEVEL="INFO"):
        configure_logging(stream=stream)
        logger = get_logger("tests.observability", component="test")
        logger.info("json_log_test", ticker="THYAO.IS", duration_ms=12.5)

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "json_log_test"
    assert payload["ticker"] == "THYAO.IS"
    assert payload["duration_ms"] == 12.5


def test_structured_log_event_includes_standard_fields():
    stream = io.StringIO()
    with settings.override(LOG_FORMAT="json", LOG_LEVEL="INFO"):
        configure_logging(stream=stream)
        logger = get_logger("tests.observability.events", component="test")
        log_event(
            "order_submitted",
            ticker="SISE.IS",
            order_id="ord-1",
            latency_ms=42.5,
            logger=logger,
            side="BUY",
        )
        log_signal("BUY", ticker="SISE.IS", score=55.0, logger=logger)
        log_order(
            "order_rejected",
            ticker="THYAO.IS",
            side="SELL",
            status="REJECTED",
            order_id="ord-2",
            error="insufficient funds",
            latency_ms=10.0,
            logger=logger,
        )
        log_risk_reject("daily_loss_cap", ticker="GARAN.IS", logger=logger)

    lines = [json.loads(line) for line in stream.getvalue().strip().splitlines() if line]
    assert len(lines) >= 4
    first = lines[0]
    assert first["event"] == "order_submitted"
    assert first["ticker"] == "SISE.IS"
    assert first["order_id"] == "ord-1"
    assert first["error"] == ""
    assert first["latency_ms"] == 42.5
    assert "timestamp" in first
    rejected = next(item for item in lines if item["event"] == "order_rejected")
    assert rejected["error"] == "insufficient funds"
    assert rejected["order_id"] == "ord-2"


def test_observability_metrics_record_and_render():
    reset_observability_metrics()
    record_signal("BUY")
    record_signal("STRONG_BUY")
    record_order("BUY", "FILLED")
    record_order("SELL", "REJECTED")
    set_positions_current(3)
    set_daily_pnl(-125.5)
    observe_order_latency(0.12)
    observe_order_latency(1.5)

    text = render_observability_metrics()
    assert 'bist_bot_signals_total{signal_type="BUY"}' in text
    assert 'bist_bot_signals_total{signal_type="STRONG_BUY"}' in text
    assert 'bist_bot_orders_total{side="BUY",status="FILLED"}' in text
    assert 'bist_bot_orders_total{side="SELL",status="REJECTED"}' in text
    assert "bist_bot_positions_current 3.0" in text or "bist_bot_positions_current 3" in text
    assert "bist_bot_pnl_daily -125.5" in text
    assert "bist_bot_order_latency_seconds" in text


def test_alert_manager_sends_webhook_payload():
    reset_alert_manager()
    sent: list[tuple[str, dict[str, Any], float]] = []

    def fake_transport(url: str, payload: dict[str, Any], timeout: float) -> bool:
        sent.append((url, payload, timeout))
        return True

    manager = AlertManager(
        webhook_url="https://hooks.example.test/alert",
        timeout_seconds=3.0,
        transport=fake_transport,
    )
    reset_alert_manager(manager)

    ok = send_alert(
        "Order rejected",
        "BUY THYAO.IS rejected by venue",
        level=AlertLevel.CRITICAL,
        ticker="THYAO.IS",
        order_id="abc",
        error="REJECTED",
    )
    assert ok is True
    assert manager.sent_count == 1
    assert len(sent) == 1
    url, payload, timeout = sent[0]
    assert url == "https://hooks.example.test/alert"
    assert timeout == 3.0
    assert payload["title"] == "Order rejected"
    assert payload["ticker"] == "THYAO.IS"
    assert payload["order_id"] == "abc"
    assert payload["level"] == "critical"
    assert "text" in payload


def test_alert_manager_skips_without_webhook():
    reset_alert_manager()
    manager = AlertManager(webhook_url="", transport=MagicMock(return_value=True))
    reset_alert_manager(manager)
    ok = manager.send(Alert(title="x", message="y", level=AlertLevel.WARNING, ticker="A.IS"))
    assert ok is False
    assert manager.sent_count == 0


def test_order_executor_records_metrics_and_alerts_on_reject():
    from datetime import UTC, datetime

    from bist_bot.execution.base import OrderResult, OrderState
    from bist_bot.execution.order_executor import OrderExecutor
    from bist_bot.strategy.signal_models import Signal, SignalType

    reset_observability_metrics()
    reset_alert_manager()
    sent: list[dict[str, Any]] = []

    def fake_transport(url: str, payload: dict[str, Any], timeout: float) -> bool:
        _ = url, timeout
        sent.append(payload)
        return True

    reset_alert_manager(
        AlertManager(webhook_url="https://hooks.example.test/x", transport=fake_transport)
    )

    broker = MagicMock()
    broker.authenticate.return_value = True
    broker.place_order.return_value = OrderResult(
        accepted=False,
        order_id="rej-1",
        state=OrderState.REJECTED,
        message="risk limit",
    )
    settings_mock = MagicMock()
    settings_mock.AUTO_EXECUTE = True
    settings_mock.AUTO_EXECUTE_WARN_MAX_QUANTITY = 100_000
    executor = OrderExecutor(broker, settings=settings_mock)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=40.0,
        price=100.0,
        position_size=2,
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    result = executor.execute_signal(signal)
    assert result is not None
    assert result.accepted is False
    text = render_observability_metrics()
    assert 'bist_bot_orders_total{side="BUY",status="REJECTED"}' in text
    assert sent and sent[0]["title"] == "Order rejected"
