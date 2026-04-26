"""Tests for dashboard healthcheck and readiness endpoints."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from flask import Flask

from bist_bot.dashboard import create_dashboard_app
from bist_bot.risk.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.ping.return_value = True
    return db


@pytest.fixture
def mock_circuit() -> MagicMock:
    circuit = MagicMock(spec=CircuitBreaker)
    circuit.state = CircuitState.CLOSED
    return circuit


@pytest.fixture
def app(mock_db, mock_circuit) -> Flask:
    from bist_bot.config.settings import settings

    fetcher = MagicMock()
    engine = MagicMock()

    with settings.override(JWT_SECRET_KEY="test-secret"):
        app = create_dashboard_app(
            fetcher=fetcher,
            engine=engine,
            db=mock_db,
            circuit_breaker=mock_circuit,
        )
    app.config["TESTING"] = True
    return app


def test_healthcheck_returns_healthy_when_db_is_up(app, mock_circuit):
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "healthy"
        assert data["database"] == "ok"
        assert "version" in data
        assert "timestamp" in data
        assert data["circuit_state"] == "CLOSED"


def test_healthcheck_shows_circuit_open_state(app, mock_circuit):
    mock_circuit.state = CircuitState.OPEN
    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["circuit_state"] == "OPEN"


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
        assert "timestamp" in data
