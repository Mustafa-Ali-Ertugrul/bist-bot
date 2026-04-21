"""Authentication and API protection tests."""

from __future__ import annotations

import os
import sys

from passlib.context import CryptContext

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dashboard import create_dashboard_app  # noqa: E402
from db import DataAccess, DatabaseManager  # noqa: E402
from config import settings  # noqa: E402


PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")


class DummyFetcher:
    def clear_cache(self) -> None:
        return None

    def fetch_multi_timeframe_all(self, **kwargs):
        _ = kwargs
        return {}

    def fetch_single(self, ticker: str, period: str = "6mo"):
        _ = ticker, period
        return None


class DummyEngine:
    def scan_all(self, data):
        _ = data
        return []

    def get_actionable_signals(self, signals):
        return signals

    def analyze(self, ticker: str, df):
        _ = ticker, df
        return None


def build_test_client(tmp_path):
    password_hash = PASSWORD_CONTEXT.hash("test-password")
    with settings.override(
        DB_PATH=str(tmp_path / "auth_test.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_EMAIL="admin@bistbot.local",
        ADMIN_PASSWORD_HASH=password_hash,
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_test.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(DummyFetcher(), DummyEngine(), db)
        app.config["TESTING"] = True
        return app.test_client()


def test_login_successful(tmp_path):
    client = build_test_client(tmp_path)

    response = client.post(
        "/api/auth/login",
        json={"email": "admin@bistbot.local", "password": "test-password"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert "access_token" in payload


def test_login_wrong_password_returns_401(tmp_path):
    client = build_test_client(tmp_path)

    response = client.post(
        "/api/auth/login",
        json={"email": "admin@bistbot.local", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_rate_limit_returns_429(tmp_path):
    client = build_test_client(tmp_path)

    last_response = None
    for _ in range(6):
        last_response = client.post(
            "/api/auth/login",
            json={"email": "admin@bistbot.local", "password": "wrong-password"},
        )

    assert last_response is not None
    assert last_response.status_code == 429


def test_scan_requires_token(tmp_path):
    client = build_test_client(tmp_path)

    response = client.post("/api/scan")

    assert response.status_code == 401
