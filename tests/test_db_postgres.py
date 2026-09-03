"""Database connection / PostgreSQL migration infrastructure tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import NullPool

from bist_bot.db.connection import (
    create_db_engine,
    is_postgres_url,
    resolve_database_url,
)
from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.signal_models import Signal, SignalType


def test_resolve_database_url_defaults_to_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BIST_BOT_DATABASE_URL", raising=False)
    db_file = tmp_path / "local.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    cfg = resolve_database_url()
    assert cfg.is_sqlite is True
    assert cfg.url.startswith("sqlite:///")
    assert "local.db" in cfg.url


def test_resolve_database_url_prefers_bist_bot_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("bist_bot.db.connection._postgres_driver_available", lambda: True)
    monkeypatch.setenv(
        "BIST_BOT_DATABASE_URL",
        "postgresql://user:pass@localhost:5432/bist_bot",
    )
    cfg = resolve_database_url()
    assert cfg.is_sqlite is False
    assert cfg.url.startswith("postgresql+psycopg2://")
    assert "bist_bot" in cfg.url


def test_resolve_database_url_normalizes_postgres_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bist_bot.db.connection._postgres_driver_available", lambda: True)
    cfg = resolve_database_url(database_url="postgres://u:p@h:5432/db")
    assert cfg.url.startswith("postgresql+psycopg2://")
    assert is_postgres_url(cfg.url)


def test_resolve_database_url_falls_back_to_sqlite_when_driver_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Postgres URL configured but psycopg2 missing → loud SQLite fallback (DB_PATH)."""
    monkeypatch.setattr("bist_bot.db.connection._postgres_driver_available", lambda: False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/bist_bot")
    db_file = tmp_path / "driver_fallback.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    cfg = resolve_database_url()
    assert cfg.is_sqlite is True
    assert cfg.url.startswith("sqlite:///")
    assert "driver_fallback.db" in cfg.url
    assert cfg.sqlite_path == str(db_file)


def test_create_db_engine_sqlite_uses_null_pool_and_check_same_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BIST_BOT_DATABASE_URL", raising=False)
    path = tmp_path / "pool.db"
    cfg = resolve_database_url(database_url="", sqlite_path=str(path))
    engine = create_db_engine(cfg)
    try:
        assert engine.pool.__class__ is NullPool
        assert cfg.is_sqlite is True
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    finally:
        engine.dispose()


def test_create_db_engine_postgres_uses_queue_pool_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bist_bot.db.connection._postgres_driver_available", lambda: True)
    mock_engine = MagicMock()
    with patch("bist_bot.db.connection.create_engine", return_value=mock_engine) as mocked:
        cfg = resolve_database_url(
            database_url="postgresql+psycopg2://user:pass@localhost:5432/bist"
        )
        # Force pool knobs
        from dataclasses import replace

        cfg = replace(cfg, pool_size=10, max_overflow=20, pool_timeout=30)
        create_db_engine(cfg)

    kwargs = mocked.call_args.kwargs
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 20
    assert kwargs["pool_timeout"] == 30
    assert kwargs["pool_pre_ping"] is True
    assert "poolclass" not in kwargs  # default QueuePool


def test_database_manager_sqlite_fallback_still_works(tmp_path: Path) -> None:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "fallback.db"))
    assert manager._is_sqlite is True
    assert manager.get_journal_mode().lower() == "wal"

    repo = SignalsRepository(manager=manager)
    signal = Signal(
        ticker="SISE.IS",
        signal_type=SignalType.BUY,
        score=12.0,
        price=50.0,
        reasons=["db-fallback"],
        timestamp=datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC),
    )
    repo.save_signal(signal)
    latest = repo.get_latest_signal("SISE.IS")
    assert latest is not None
    assert latest["ticker"] == "SISE.IS"
    manager.session_factory.remove()
    manager.engine.dispose()


def test_database_manager_uses_connection_factory_for_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bist_bot.db.connection._postgres_driver_available", lambda: True)
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = MagicMock()
    mock_engine.begin.return_value.__exit__.return_value = False
    mock_session_factory = MagicMock()

    with (
        patch(
            "bist_bot.db.connection.create_engine", return_value=mock_engine
        ) as create_engine_mock,
        patch("bist_bot.db.database.scoped_session", return_value=mock_session_factory),
        patch.object(DatabaseManager, "initialize", return_value=None),
    ):
        manager = DatabaseManager(
            database_url="postgresql://user:pass@host/db",
            pool_size=10,
            max_overflow=20,
        )

    assert manager._is_sqlite is False
    create_engine_mock.assert_called_once()
    engine_url = create_engine_mock.call_args.args[0]
    engine_kwargs = create_engine_mock.call_args.kwargs
    assert engine_url.startswith("postgresql+psycopg2://")
    assert engine_kwargs["pool_size"] == 10
    assert engine_kwargs["max_overflow"] == 20
    assert engine_kwargs["pool_pre_ping"] is True


def test_database_manager_postgres_url_falls_back_to_sqlite_without_driver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DATABASE_URL=postgres + no psycopg2 installed → DatabaseManager runs on SQLite."""
    monkeypatch.setattr("bist_bot.db.connection._postgres_driver_available", lambda: False)
    manager = DatabaseManager(
        database_url="postgresql://user:pass@localhost:5432/bist_bot",
        sqlite_path=str(tmp_path / "manager_fallback.db"),
    )
    try:
        assert manager._is_sqlite is True
        assert manager.get_journal_mode().lower() == "wal"
    finally:
        manager.session_factory.remove()
        manager.engine.dispose()


def test_alembic_initial_revision_file_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    rev = root / "alembic" / "versions" / "0001_initial_schema.py"
    assert rev.exists()
    text = rev.read_text(encoding="utf-8")
    assert "create_table" in text
    assert "signals" in text
    assert "scan_log" in text
    assert "paper_trades" in text
    assert (
        'revision: str = "0001_initial_schema"' in text
        or 'revision: str = "0001_initial_schema"' in text
    )


@pytest.mark.integration
def test_live_postgres_optional() -> None:
    """Optional live Postgres smoke test when DATABASE_URL is configured."""
    url = (os.environ.get("DATABASE_URL") or os.environ.get("BIST_BOT_DATABASE_URL") or "").strip()
    if not url or url.startswith("sqlite"):
        pytest.skip("DATABASE_URL not configured for live Postgres")
    try:
        manager = DatabaseManager(database_url=url)
    except (RuntimeError, Exception) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Postgres not available: {exc}")
    try:
        with manager.engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    finally:
        manager.session_factory.remove()
        manager.engine.dispose()
