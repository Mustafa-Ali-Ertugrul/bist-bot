"""Authentication and API protection tests."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

import bcrypt

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dashboard import create_dashboard_app  # noqa: E402
from bist_bot.auth.passwords import hash_password  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from sqlalchemy import text  # noqa: E402


class DummyFetcher:
    def clear_cache(self) -> None:
        return None

    def fetch_all(self, period: str = "3mo", interval: str = "1d"):
        _ = period, interval
        return {}

    def fetch_multi_timeframe_all(
        self,
        trend_period: str = "6mo",
        trend_interval: str = "1d",
        trigger_period: str = "1mo",
        trigger_interval: str = "15m",
    ):
        _ = trend_period, trend_interval, trigger_period, trigger_interval
        return {}

    def fetch_single(
        self,
        ticker: str,
        period: str = "6mo",
        interval: str = "1d",
        force: bool = False,
    ):
        _ = ticker, period, interval, force
        return None


class DummyEngine:
    def scan_all(self, data):
        _ = data
        return []

    def get_actionable_signals(self, signals):
        return signals

    def analyze(self, ticker: str, df, enforce_sector_limit: bool = False):
        _ = ticker, df, enforce_sector_limit
        return None


def build_test_client(tmp_path):
    password_hash = hash_password("test-password")
    with settings.override(
        DB_PATH=str(tmp_path / "auth_test.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="admin@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=password_hash,
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_test.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(
            cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db
        )
        app.config["TESTING"] = True
        return app.test_client()


def build_db_user_client(tmp_path, *, include_bootstrap: bool = False):
    override_kwargs = {
        "DB_PATH": str(tmp_path / "auth_db_only.db"),
        "JWT_SECRET_KEY": "test_secret_key_12345678901234567890",
        "CORS_ORIGINS": ("http://localhost:8501",),
        "ADMIN_BOOTSTRAP_EMAIL": "",
        "ADMIN_BOOTSTRAP_PASSWORD_HASH": "",
    }
    if include_bootstrap:
        override_kwargs["ADMIN_BOOTSTRAP_EMAIL"] = "bootstrap@bistbot.local"
        override_kwargs["ADMIN_BOOTSTRAP_PASSWORD_HASH"] = hash_password(
            "bootstrap-password"
        )

    with settings.override(**override_kwargs):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_db_only.db"))
        with manager.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, role, created_at, updated_at)
                    VALUES (:email, :password_hash, 'admin', :created_at, :updated_at)
                    """
                ),
                {
                    "email": "dbadmin@bistbot.local",
                    "password_hash": hash_password("db-password"),
                    "created_at": manager.now_iso(),
                    "updated_at": manager.now_iso(),
                },
            )
        db = DataAccess(manager)
        app = create_dashboard_app(
            cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db
        )
        app.config["TESTING"] = True
        return app.test_client(), manager


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


def test_register_creates_user_and_returns_token(tmp_path):
    client, manager = build_db_user_client(tmp_path)

    response = client.post(
        "/api/auth/register",
        json={"email": "newuser@bistbot.local", "password": "strong-pass-123"},
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload is not None
    assert "access_token" in payload

    with manager.engine.begin() as conn:
        stored_hash = conn.execute(
            text("SELECT password_hash FROM users WHERE email = :email"),
            {"email": "newuser@bistbot.local"},
        ).scalar_one()
    assert isinstance(stored_hash, str)
    assert stored_hash.startswith("scrypt:")


def test_register_rejects_duplicate_email(tmp_path):
    client, _manager = build_db_user_client(tmp_path)

    response = client.post(
        "/api/auth/register",
        json={"email": "dbadmin@bistbot.local", "password": "strong-pass-123"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["message"] == "Bu email zaten kayitli"


def test_register_rejects_short_password(tmp_path):
    client, _manager = build_db_user_client(tmp_path)

    response = client.post(
        "/api/auth/register",
        json={"email": "short@bistbot.local", "password": "short"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["message"] == "Sifre en az 8 karakter olmali"


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


def test_login_uses_existing_db_user_without_env_admin(tmp_path):
    client, _manager = build_db_user_client(tmp_path)

    response = client.post(
        "/api/auth/login",
        json={"email": "dbadmin@bistbot.local", "password": "db-password"},
    )

    assert response.status_code == 200


def test_existing_db_users_prevent_env_bootstrap_override(tmp_path):
    client, manager = build_db_user_client(tmp_path)

    with settings.override(
        DB_PATH=str(tmp_path / "auth_db_only.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        CORS_ORIGINS=("http://localhost:8501",),
        ADMIN_BOOTSTRAP_EMAIL="bootstrap@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("bootstrap-password"),
    ):
        db = DataAccess(manager)
        app = create_dashboard_app(
            cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db
        )
        app.config["TESTING"] = True
        client = app.test_client()

    response = client.post(
        "/api/auth/login",
        json={"email": "bootstrap@bistbot.local", "password": "bootstrap-password"},
    )
    assert response.status_code == 401

    with manager.engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
    assert count == 1


def test_missing_jwt_secret_prevents_app_startup(tmp_path):
    with settings.override(
        DB_PATH=str(tmp_path / "auth_missing_jwt.db"),
        JWT_SECRET_KEY="",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_missing_jwt.db"))
        db = DataAccess(manager)

        try:
            create_dashboard_app(
                cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db
            )
        except RuntimeError as exc:
            assert "JWT_SECRET_KEY" in str(exc)
        else:
            raise AssertionError(
                "Expected create_dashboard_app to fail without JWT secret"
            )


def test_legacy_bcrypt_hash_migrates_on_successful_login(tmp_path):
    legacy_hash = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode("utf-8")
    with settings.override(
        DB_PATH=str(tmp_path / "auth_legacy.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_legacy.db"))
        with manager.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, role, created_at, updated_at)
                    VALUES (:email, :password_hash, 'admin', :created_at, :updated_at)
                    """
                ),
                {
                    "email": "legacy@bistbot.local",
                    "password_hash": legacy_hash,
                    "created_at": manager.now_iso(),
                    "updated_at": manager.now_iso(),
                },
            )
        db = DataAccess(manager)
        app = create_dashboard_app(
            cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db
        )
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.post(
            "/api/auth/login",
            json={"email": "legacy@bistbot.local", "password": "legacy-password"},
        )

        assert response.status_code == 200
        with manager.engine.begin() as conn:
            migrated_hash = conn.execute(
                text("SELECT password_hash FROM users WHERE email = :email"),
                {"email": "legacy@bistbot.local"},
            ).scalar_one()
        assert isinstance(migrated_hash, str)
        assert migrated_hash.startswith("scrypt:")
