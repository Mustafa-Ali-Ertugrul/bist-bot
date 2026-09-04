from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from bist_bot.auth.passwords import hash_password
from bist_bot.config.settings import settings
from bist_bot.db import DatabaseManager


def test_enforce_mode_refuses_startup_without_privileged_user(tmp_path) -> None:
    db_path = str(tmp_path / "no-admin.db")
    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="enforce",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        with pytest.raises(RuntimeError, match="No admin/trader user exists"):
            DatabaseManager(sqlite_path=db_path)


def test_enforce_mode_bootstraps_first_admin(tmp_path) -> None:
    db_path = str(tmp_path / "bootstrap-admin.db")
    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="enforce",
        ADMIN_BOOTSTRAP_EMAIL="admin@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("bootstrap-password"),
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        with manager.engine.connect() as conn:
            role = conn.execute(
                text("SELECT role FROM users WHERE email = :email"),
                {"email": "admin@bistbot.local"},
            ).scalar_one()

    assert role == "admin"


def test_bootstrap_update_promotes_existing_user_when_explicitly_enabled(tmp_path) -> None:
    db_path = str(tmp_path / "promote-admin.db")
    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="warn",
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        now = datetime.now(UTC)
        with manager.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users "
                    "(email, password_hash, role, created_at, updated_at) "
                    "VALUES (:email, :password_hash, 'user', :created_at, :updated_at)"
                ),
                {
                    "email": "admin@bistbot.local",
                    "password_hash": hash_password("old-password"),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        manager.engine.dispose()

    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="enforce",
        ADMIN_BOOTSTRAP_EMAIL="admin@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("new-password"),
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=True,
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        with manager.engine.connect() as conn:
            role = conn.execute(
                text("SELECT role FROM users WHERE email = :email"),
                {"email": "admin@bistbot.local"},
            ).scalar_one()

    assert role == "admin"
