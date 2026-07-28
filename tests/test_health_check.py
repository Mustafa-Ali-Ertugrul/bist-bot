"""Tests for dashboard /health and /ready probes (Docker / Cloud Run)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from flask import Flask

from bist_bot.dashboard import create_dashboard_app
from bist_bot.risk.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.ping.return_value = True
    db.get_latest_scan_log.return_value = {
        "timestamp": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        "total_scanned": 10,
        "signals_generated": 2,
    }
    return db


@pytest.fixture
def mock_circuit() -> MagicMock:
    circuit = MagicMock(spec=CircuitBreaker)
    circuit.state = CircuitState.CLOSED
    return circuit


@pytest.fixture
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.authenticate.return_value = True
    return broker


@pytest.fixture
def app(mock_db, mock_circuit, mock_broker) -> Flask:
    from bist_bot.config.settings import settings

    with settings.override(
        JWT_SECRET_KEY="test-secret",
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
    ):
        fetcher = MagicMock()
        engine = MagicMock()
        application = create_dashboard_app(
            fetcher=fetcher,
            engine=engine,
            db=mock_db,
            broker=mock_broker,
            circuit_breaker=mock_circuit,
        )
        application.config["TESTING"] = True
        return application


def test_health_check_returns_healthy_when_db_is_up(app, mock_circuit):
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "healthy"
        assert data["database"] == "ok"
        assert "version" in data
        assert "timestamp" in data
        assert data["circuit_state"] == "CLOSED"
        assert "broker" in data
        assert data["broker"]["status"] == "ok"
        assert data["last_scan"]["timestamp"] is not None
        assert data["last_scan"]["age_seconds"] is not None


def test_health_check_shows_circuit_open_without_failing_probe(app, mock_circuit):
    mock_circuit.state = CircuitState.OPEN
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["circuit_state"] == "OPEN"
        assert data["status"] == "healthy"


def test_health_check_returns_degraded_when_db_is_down(app, mock_db):
    mock_db.ping.return_value = False
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 503
        data = json.loads(resp.data)
        assert data["status"] == "degraded"
        assert data["database"] == "error"


def test_health_check_broker_auth_failure_degrades(app, mock_broker):
    from bist_bot.config.settings import settings

    mock_broker.authenticate.return_value = False
    with settings.override(
        JWT_SECRET_KEY="test-secret",
        BROKER_MODE="live",
        BROKER_PROVIDER="algolab",
        ALGOLAB_API_KEY="test-key",
        ALGOLAB_USERNAME="test-user",
        ALGOLAB_PASSWORD="test-pass",
        ALGOLAB_OTP_CODE="",
        ALGOLAB_DRY_RUN=True,
    ):
        # Rebuild app with live mode so authenticate is probed
        from bist_bot.dashboard import create_dashboard_app

        fetcher = MagicMock()
        engine = MagicMock()
        db = MagicMock()
        db.ping.return_value = True
        db.get_latest_scan_log.return_value = None
        circuit = MagicMock(spec=CircuitBreaker)
        circuit.state = CircuitState.CLOSED
        application = create_dashboard_app(
            fetcher=fetcher,
            engine=engine,
            db=db,
            broker=mock_broker,
            circuit_breaker=circuit,
        )
        application.config["TESTING"] = True
        with application.test_client() as client:
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["status"] == "degraded"
            assert data["broker"]["status"] == "auth_failed"


def test_readiness_check_returns_ok(app):
    with app.test_client() as client:
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ready"
        assert "timestamp" in data


def test_metrics_requires_auth_by_default(app):
    with app.test_client() as client:
        resp = client.get("/metrics")
        assert resp.status_code == 401


def test_metrics_public_when_enabled(mock_db, mock_circuit, mock_broker):
    from bist_bot.config.settings import settings

    with settings.override(
        JWT_SECRET_KEY="test-secret",
        METRICS_PUBLIC=True,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=mock_db,
            broker=mock_broker,
            circuit_breaker=mock_circuit,
        )
        application.config["TESTING"] = True
        with application.test_client() as client:
            resp = client.get("/metrics")
            assert resp.status_code == 200
            body = resp.get_data(as_text=True)
            assert "bist_scan_total" in body or "bist_bot_" in body
