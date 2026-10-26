from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from bist_bot.auth.passwords import hash_password
from bist_bot.config.settings import settings
from bist_bot.db import DatabaseManager


def test_rbac_mode_defaults_to_enforce() -> None:
    """Production posture: privileged routes deny unless a deployment opts in.

    The default lives in a dataclass field (evaluated at import time), so it is
    checked in a fresh interpreter — a module reload elsewhere in the suite
    would otherwise make this order-dependent.
    """
    import os
    import subprocess
    import sys

    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    code = "from bist_bot.config.subsettings import AuthSettings; print(AuthSettings().RBAC_MODE)"

    def run(env_value: str | None) -> str:
        env = {k: v for k, v in os.environ.items() if k != "RBAC_MODE"}
        env["PYTHONPATH"] = src_dir
        if env_value is not None:
            env["RBAC_MODE"] = env_value
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    assert run(None) == "enforce"
    assert run("") == "enforce"


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
            audit_event = conn.execute(
                text(
                    "SELECT event_type FROM audit_trail "
                    "WHERE event_type = 'admin_bootstrap_created'"
                )
            ).scalar_one()

    assert role == "admin"
    assert audit_event == "admin_bootstrap_created"


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
            audit_event = conn.execute(
                text(
                    "SELECT event_type FROM audit_trail "
                    "WHERE event_type = 'admin_bootstrap_promoted_existing'"
                )
            ).scalar_one()

    assert role == "admin"
    assert audit_event == "admin_bootstrap_promoted_existing"


def test_bootstrap_update_flag_cannot_rearm_via_marker_deletion(tmp_path) -> None:
    """AppSec: clearing the per-email bootstrap marker must not re-enable the
    env-driven admin overwrite — the global first-boot marker still refuses it."""
    db_path = str(tmp_path / "bootstrap-flag-expiry.db")
    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="warn",
        ADMIN_BOOTSTRAP_EMAIL="admin@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("first-password"),
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=True,
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        with manager.engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM bootstrap_state "
                    "WHERE key = 'admin_bootstrap_completed:admin@bistbot.local'"
                )
            )
        manager.engine.dispose()

    with settings.override(
        DB_PATH=db_path,
        DATABASE_URL="",
        RBAC_MODE="warn",
        ADMIN_BOOTSTRAP_EMAIL="admin@bistbot.local",
        ADMIN_BOOTSTRAP_PASSWORD_HASH=hash_password("attacker-password"),
        ADMIN_BOOTSTRAP_UPDATE_EXISTING=True,
    ):
        with pytest.raises(RuntimeError, match="already completed on this database"):
            DatabaseManager(sqlite_path=db_path)
