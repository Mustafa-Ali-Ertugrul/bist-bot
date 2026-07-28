"""Legacy filename for health probes — canonical suite is test_health_check.py."""

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
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=mock_db,
            broker=mock_broker,
            circuit_breaker=mock_circuit,
        )
        application.config["TESTING"] = True
        return application


def test_healthcheck_returns_healthy_when_db_is_up(app, mock_circuit):
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "healthy"
        assert data["database"] == "ok"
        assert data["circuit_state"] == "CLOSED"


def test_healthcheck_shows_circuit_open_state(app, mock_circuit):
    mock_circuit.state = CircuitState.OPEN
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["circuit_state"] == "OPEN"
        assert data["status"] == "healthy"


def test_healthcheck_returns_degraded_when_db_is_down(app, mock_db):
    mock_db.ping.return_value = False
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 503
        data = json.loads(resp.data)
        assert data["status"] == "degraded"
        assert data["database"] == "error"


def test_readiness_check_returns_ok(app):
    with app.test_client() as client:
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ready"
