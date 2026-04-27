"""Observability tests for metrics and structured logging."""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any, cast

from flask_jwt_extended import create_access_token

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dashboard import create_dashboard_app  # noqa: E402
from bist_bot.app_logging import configure_logging, get_logger  # noqa: E402
from bist_bot.app_metrics import reset_metrics  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


class MetricsFetcher:
    def clear_cache(self, scope: str = "all", ticker: str | None = None, period: str | None = None, interval: str | None = None) -> None:
        _ = scope, ticker, period, interval

    def fetch_all(self, period: str = "3mo", interval: str = "1d", force: bool = False):
        _ = period, interval, force
        return {}

    def fetch_multi_timeframe_all(
        self,
        trend_period: str = '6mo',
        trend_interval: str = '1d',
        trigger_period: str = '1mo',
        trigger_interval: str = '15m',
        force_refresh: bool = False,
        limit: int | None = None,
    ):
        _ = trend_period, trend_interval, trigger_period, trigger_interval, force_refresh, limit
        return {"THYAO.IS": {"trend": object(), "trigger": object()}}

    def fetch_single(self, ticker: str, period: str = "6mo", interval: str = "1d", force: bool = False):
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


def _build_client(tmp_path):
    reset_metrics()
    with settings.override(
        DB_PATH=str(tmp_path / "observability.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "observability.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, MetricsFetcher()), cast(Any, MetricsEngine()), db)
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
    client, _token = _build_client(tmp_path)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "bist_scan_total" in response.get_data(as_text=True)


def test_scan_updates_metrics_counters(tmp_path):
    client, token = _build_client(tmp_path)

    scan_response = client.post("/api/scan", headers={"Authorization": f"Bearer {token}"})
    metrics_response = client.get("/metrics")

    assert scan_response.status_code == 200
    metrics_text = metrics_response.get_data(as_text=True)
    assert _metric_value(metrics_text, "bist_scan_total") == 1.0
    assert _metric_value(metrics_text, "bist_signal_emitted_total") == 1.0
    assert _metric_value(metrics_text, "bist_last_scan_scanned_count") == 1.0


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
