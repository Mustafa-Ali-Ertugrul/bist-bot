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
from sqlalchemy import text  # noqa: E402

from bist_bot.auth.passwords import hash_password  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402


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
        force_refresh: bool = False,
    ):
        _ = trend_period, trend_interval, trigger_period, trigger_interval, force_refresh
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

    def get_last_rejection_breakdown(self):
        return {"total_rejections": 0, "by_reason": [], "by_stage": [], "scan_id": ""}


def build_test_client(tmp_path):
    with settings.override(
        DB_PATH=str(tmp_path / "auth_test.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_test.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        app.config["ALLOW_PUBLIC_REGISTRATION"] = True
        return app.test_client()


def build_db_user_client(
    tmp_path,
    *,
    include_bootstrap: bool = False,
    allow_public_registration: bool = False,
):
    override_kwargs = {
        "DB_PATH": str(tmp_path / "auth_db_only.db"),
        "JWT_SECRET_KEY": "test_secret_key_12345678901234567890",
        "CORS_ORIGINS": ("http://localhost:8501",),
        "ADMIN_BOOTSTRAP_EMAIL": "",
        "ADMIN_BOOTSTRAP_PASSWORD_HASH": "",
        "ALLOW_PUBLIC_REGISTRATION": allow_public_registration,
    }
    if include_bootstrap:
        override_kwargs["ADMIN_BOOTSTRAP_EMAIL"] = "bootstrap@bistbot.local"
        override_kwargs["ADMIN_BOOTSTRAP_PASSWORD_HASH"] = hash_password("bootstrap-password")

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
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        return app.test_client(), manager


def test_login_successful(tmp_path):
    client = build_test_client(tmp_path)

    # Önce kullanıcıyı oluştur
    response = client.post(
        "/api/auth/register",
        json={"email": "admin@bistbot.local", "password": "test-password"},
    )
    assert response.status_code == 201

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
    client, manager = build_db_user_client(tmp_path, allow_public_registration=True)

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


def test_register_returns_403_when_public_registration_disabled(tmp_path):
    client, manager = build_db_user_client(tmp_path)

    response = client.post(
        "/api/auth/register",
        json={"email": "newuser@bistbot.local", "password": "strong-pass-123"},
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload is not None
    assert payload["message"] == "Herkese acik kayit kapali"

    with manager.engine.begin() as conn:
        stored_count = conn.execute(
            text("SELECT COUNT(*) FROM users WHERE email = :email"),
            {"email": "newuser@bistbot.local"},
        ).scalar_one()
    assert stored_count == 0


def test_stats_endpoint_returns_stable_rejection_breakdown_shape(tmp_path):
    client, manager = build_db_user_client(tmp_path)

    login_response = client.post(
        "/api/auth/login",
        json={"email": "dbadmin@bistbot.local", "password": "db-password"},
    )
    assert login_response.status_code == 200
    payload = login_response.get_json()
    assert payload is not None
    token = payload["access_token"]

    db = DataAccess(manager)
    db.save_latest_rejection_breakdown(
        {
            "total_rejections": 3,
            "by_reason": [
                {"reason_code": "score_filtered_sideways", "count": 2},
                {"reason_code": "insufficient_history", "count": 1},
            ],
            "by_stage": [
                {"stage": "scoring", "count": 2},
                {"stage": "data", "count": 1},
            ],
            "scan_id": "scan-api123",
        }
    )

    response = client.get("/api/stats", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    breakdown = data["rejection_breakdown"]
    assert breakdown == {
        "total_rejections": 3,
        "by_reason": [
            {"reason_code": "score_filtered_sideways", "count": 2},
            {"reason_code": "insufficient_history", "count": 1},
        ],
        "by_stage": [
            {"stage": "scoring", "count": 2},
            {"stage": "data", "count": 1},
        ],
        "scan_id": "scan-api123",
    }
    assert data["stats"]["rejection_breakdown"] == breakdown


def test_stats_endpoint_returns_empty_rejection_breakdown_when_missing(tmp_path):
    client, _manager = build_db_user_client(tmp_path)

    login_response = client.post(
        "/api/auth/login",
        json={"email": "dbadmin@bistbot.local", "password": "db-password"},
    )
    assert login_response.status_code == 200
    payload = login_response.get_json()
    assert payload is not None

    response = client.get(
        "/api/stats",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["rejection_breakdown"] == {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "",
    }


def test_scan_log_persists_rejection_snapshot_history(tmp_path):
    _client, manager = build_db_user_client(tmp_path)
    db = DataAccess(manager)

    db.save_scan_log(
        20,
        6,
        3,
        1,
        4,
        scan_id="scan-persist",
        rejection_breakdown={
            "total_rejections": 8,
            "by_reason": [{"reason_code": "score_filtered_sideways", "count": 5}],
            "by_stage": [{"stage": "scoring", "count": 5}],
            "scan_id": "scan-persist",
        },
    )

    rows = db.get_recent_scan_logs(limit=1)

    assert len(rows) == 1
    assert rows[0]["scan_id"] == "scan-persist"
    assert rows[0]["rejection_breakdown"] == {
        "total_rejections": 8,
        "by_reason": [{"reason_code": "score_filtered_sideways", "count": 5}],
        "by_stage": [{"stage": "scoring", "count": 5}],
        "scan_id": "scan-persist",
    }


def test_scan_history_endpoint_returns_aggregated_history(tmp_path):
    client, manager = build_db_user_client(tmp_path)

    login_response = client.post(
        "/api/auth/login",
        json={"email": "dbadmin@bistbot.local", "password": "db-password"},
    )
    assert login_response.status_code == 200
    payload = login_response.get_json()
    assert payload is not None
    token = payload["access_token"]

    db = DataAccess(manager)
    db.save_scan_log(
        20,
        6,
        3,
        1,
        4,
        scan_id="scan-002",
        rejection_breakdown={
            "total_rejections": 8,
            "by_reason": [{"reason_code": "score_filtered_sideways", "count": 5}],
            "by_stage": [{"stage": "scoring", "count": 5}],
            "scan_id": "scan-002",
        },
    )
    db.save_scan_log(
        20,
        4,
        2,
        0,
        2,
        scan_id="scan-001",
        rejection_breakdown={
            "total_rejections": 2,
            "by_reason": [{"reason_code": "insufficient_history", "count": 2}],
            "by_stage": [{"stage": "data", "count": 2}],
            "scan_id": "scan-001",
        },
    )

    response = client.get(
        "/api/scans/history?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    history = data["history"]
    assert history["window_size"] == 2
    assert history["returned_scans"] == 2
    assert history["by_reason"][0] == {"reason_code": "score_filtered_sideways", "count": 5}
    assert history["by_stage"][0] == {"stage": "scoring", "count": 5}
    assert (
        history["scans"][0]["scan_id"] == "scan-001" or history["scans"][0]["scan_id"] == "scan-002"
    )
    assert {scan["scan_id"] for scan in history["scans"]} == {"scan-001", "scan-002"}
    assert history["average_rejection_rate"] == 25.0


def test_scan_history_endpoint_returns_empty_shape_without_scans(tmp_path):
    client, _manager = build_db_user_client(tmp_path)

    login_response = client.post(
        "/api/auth/login",
        json={"email": "dbadmin@bistbot.local", "password": "db-password"},
    )
    assert login_response.status_code == 200
    payload = login_response.get_json()
    assert payload is not None

    response = client.get(
        "/api/scans/history?limit=5",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["history"] == {
        "window_size": 5,
        "returned_scans": 0,
        "average_rejection_rate": 0.0,
        "by_reason": [],
        "by_stage": [],
        "scans": [],
    }


def test_register_rejects_duplicate_email(tmp_path):
    client, _manager = build_db_user_client(tmp_path, allow_public_registration=True)

    response = client.post(
        "/api/auth/register",
        json={"email": "dbadmin@bistbot.local", "password": "strong-pass-123"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["message"] == "Bu email zaten kayitli"


def test_register_rejects_short_password(tmp_path):
    client, _manager = build_db_user_client(tmp_path, allow_public_registration=True)

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


def test_existing_db_users_do_not_block_admin_seed(tmp_path):
    """Other users in the DB should not prevent admin bootstrap from creating the configured admin."""
    import sqlite3

    db_path = str(tmp_path / "auth_other_users.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at, updated_at) VALUES (?, ?, 'admin', datetime('now'), datetime('now'))",
        ("dbadmin@bistbot.local", hash_password("db-password")),
    )
    conn.commit()
    conn.close()

    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        CORS_ORIGINS=("http://localhost:8501",),
        ADMIN_BOOTSTRAP_EMAIL="bootstrap@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("bootstrap-password"),
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        client = app.test_client()

    response = client.post(
        "/api/auth/login",
        json={"email": "bootstrap@bistbot.local", "password": "bootstrap-password"},
    )
    assert response.status_code == 200

    with manager.engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
    assert count == 2


def test_existing_admin_email_blocks_duplicate_seed(tmp_path):
    """If the configured admin email already exists, bootstrap should skip."""
    import sqlite3

    admin_email = "bootstrap@bistbot.local"
    db_path = str(tmp_path / "auth_admin_exists.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at, updated_at) VALUES (?, ?, 'admin', datetime('now'), datetime('now'))",
        (admin_email, hash_password("original-password")),
    )
    conn.commit()
    conn.close()

    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        CORS_ORIGINS=("http://localhost:8501",),
        ADMIN_BOOTSTRAP_EMAIL=admin_email,
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("original-password"),
    ):
        manager = DatabaseManager(sqlite_path=db_path)

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
            create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        except RuntimeError as exc:
            assert "JWT_SECRET_KEY" in str(exc)
        else:
            raise AssertionError("Expected create_dashboard_app to fail without JWT secret")


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
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
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


def test_admin_seed_creates_loginable_user(tmp_path):
    """When bootstrap env vars are set and users table is empty, seed creates a loginable user."""
    password = "bootstrap-secret-123"
    password_hash = hash_password(password)
    with settings.override(
        DB_PATH=str(tmp_path / "auth_bootstrap.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="bootstrap@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=password_hash,
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_bootstrap.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.post(
            "/api/auth/login",
            json={"email": "bootstrap@bistbot.local", "password": password},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert "access_token" in payload


def test_admin_seed_wrong_password_returns_401(tmp_path):
    """When bootstrap env vars are set but password is wrong, login returns 401."""
    password_hash = hash_password("correct-password")
    with settings.override(
        DB_PATH=str(tmp_path / "auth_bootstrap_wrong.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="bootstrap@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=password_hash,
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_bootstrap_wrong.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.post(
            "/api/auth/login",
            json={"email": "bootstrap@bistbot.local", "password": "wrong-password"},
        )
        assert response.status_code == 401


def test_no_admin_seed_no_crash(tmp_path):
    """When bootstrap env vars are not set, app starts normally without crashing."""
    with settings.override(
        DB_PATH=str(tmp_path / "auth_no_seed.db"),
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
        CORS_ORIGINS=("http://localhost:8501",),
    ):
        manager = DatabaseManager(sqlite_path=str(tmp_path / "auth_no_seed.db"))
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.post(
            "/api/auth/login",
            json={"email": "nobody@bistbot.local", "password": "anything"},
        )
        assert response.status_code == 401


def test_existing_admin_not_updated_by_default(tmp_path):
    """Existing admin password hash must not change unless ADMIN_BOOTSTRAP_UPDATE_EXISTING=true."""
    import sqlite3

    admin_email = "bootstrap@bistbot.local"
    db_path = str(tmp_path / "auth_no_update.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    original_hash = hash_password("original-password")
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at, updated_at) VALUES (?, ?, 'admin', datetime('now'), datetime('now'))",
        (admin_email, original_hash),
    )
    conn.commit()
    conn.close()

    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        CORS_ORIGINS=("http://localhost:8501",),
        ADMIN_BOOTSTRAP_EMAIL=admin_email,
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("new-password"),
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=False,
    ):
        manager = DatabaseManager(sqlite_path=db_path)

    with manager.engine.begin() as conn:
        stored_hash = conn.execute(
            text("SELECT password_hash FROM users WHERE email = :email"),
            {"email": admin_email},
        ).scalar_one()
    assert stored_hash == original_hash


def test_existing_admin_updated_when_flag_true(tmp_path):
    """When ADMIN_BOOTSTRAP_UPDATE_EXISTING=true, existing admin hash should be replaced."""
    import sqlite3

    admin_email = "bootstrap@bistbot.local"
    db_path = str(tmp_path / "auth_update.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    old_hash = hash_password("old-password")
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at, updated_at) VALUES (?, ?, 'admin', datetime('now'), datetime('now'))",
        (admin_email, old_hash),
    )
    conn.commit()
    conn.close()

    new_hash = hash_password("new-password")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        CORS_ORIGINS=("http://localhost:8501",),
        ADMIN_BOOTSTRAP_EMAIL=admin_email,
        ADMIN_BOOTSTRAP_PASSWORD_HASH=new_hash,
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=True,
    ):
        manager = DatabaseManager(sqlite_path=db_path)

    with manager.engine.begin() as conn:
        stored_hash = conn.execute(
            text("SELECT password_hash FROM users WHERE email = :email"),
            {"email": admin_email},
        ).scalar_one()
    assert stored_hash == new_hash


def test_updated_admin_can_login_with_new_password(tmp_path):
    """After admin hash is updated via bootstrap flag, login should succeed with new password."""
    import sqlite3

    admin_email = "bootstrap@bistbot.local"
    db_path = str(tmp_path / "auth_login_after_update.db")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at, updated_at) VALUES (?, ?, 'admin', datetime('now'), datetime('now'))",
        (admin_email, hash_password("old-wrong-password")),
    )
    conn.commit()
    conn.close()

    new_password = "new-correct-password"
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test_secret_key_12345678901234567890",
        CORS_ORIGINS=("http://localhost:8501",),
        ADMIN_BOOTSTRAP_EMAIL=admin_email,
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password(new_password),
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=True,
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        db = DataAccess(manager)
        app = create_dashboard_app(cast(Any, DummyFetcher()), cast(Any, DummyEngine()), db)
        app.config["TESTING"] = True
        client = app.test_client()

    response = client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": new_password},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "access_token" in data
