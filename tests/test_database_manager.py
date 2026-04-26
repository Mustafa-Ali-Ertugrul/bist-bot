"""Database manager WAL and repository tests."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.db.database import DatabaseManager  # noqa: E402
from bist_bot.db.repositories.signals_repository import SignalsRepository  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402
from bist_bot.config import settings  # noqa: E402


def test_database_manager_enables_wal_mode(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "wal_test.db"))

    assert manager.get_journal_mode().lower() == "wal"


def test_signal_database_saves_and_reads_signal(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "signals.db"))
    db = SignalsRepository(manager=manager)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=22.5,
        price=123.45,
        reasons=["RSI low", "Volume confirmation"],
        stop_loss=118.0,
        target_price=135.0,
        confidence="ORTA",
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )

    db.save_signal(signal)
    latest = db.get_latest_signal("THYAO.IS")

    assert latest is not None
    assert latest["ticker"] == "THYAO.IS"
    assert latest["signal_type"] == SignalType.BUY.value
    assert latest["conditions"] == ["RSI low", "Volume confirmation"]
    assert latest["target_price"] == 135.0


def test_database_manager_uses_database_url_for_non_sqlite_backends():
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = MagicMock()
    mock_engine.begin.return_value.__exit__.return_value = False
    mock_session_factory = MagicMock()

    with patch(
        "bist_bot.db.database.create_engine", return_value=mock_engine
    ) as mock_create_engine:
        with patch(
            "bist_bot.db.database.scoped_session", return_value=mock_session_factory
        ):
            with patch.object(DatabaseManager, "initialize", return_value=None):
                manager = DatabaseManager(
                    database_url="postgresql+psycopg2://user:pass@host/db"
                )

    assert manager.get_journal_mode() == "n/a"
    # Verify create_engine was called with the URL from DATABASE_URL
    mock_create_engine.assert_called_once()
    engine_url = mock_create_engine.call_args.args[0]
    engine_kwargs = mock_create_engine.call_args.kwargs
    assert engine_url == "postgresql+psycopg2://user:pass@host/db"
    assert engine_kwargs["pool_pre_ping"] is True
    assert "connect_args" not in engine_kwargs


def test_nested_missing_parent_dir_created(tmp_path):
    """Test that missing parent directories are created for SQLite path."""
    db_path = tmp_path / "nested" / "missing" / "test.db"
    manager = DatabaseManager(sqlite_path=str(db_path))
    manager.initialize()
    assert db_path.parent.exists()
    assert db_path.exists()


def test_database_url_env_var_priority_over_db_path():
    """Test that DATABASE_URL takes priority over sqlite_path and DB_PATH."""

    tmp_db = Path(tempfile.mkdtemp()) / "env_url.db"
    should_not_use_db = Path(tempfile.mkdtemp()) / "should_not_use.db"

    with settings.override(DATABASE_URL=f"sqlite:///{tmp_db}"):
        with settings.override(DB_PATH=str(should_not_use_db)):
            manager = DatabaseManager()
            assert str(manager.engine.url) == f"sqlite:///{tmp_db}"
            assert not should_not_use_db.exists()


def test_db_path_falls_back_to_tmp_bist_signals_db():
    """Test that DB_PATH falls back to /tmp/bist_signals.db when not set."""

    with settings.override(DB_PATH=None, DATABASE_URL=None):
        manager = DatabaseManager()
        assert str(manager.sqlite_path) == "/tmp/bist_signals.db"


def test_tmp_bist_signals_db_initialization_succeeds():
    """Test that initialization succeeds when using /tmp/bist_signals.db."""

    with settings.override(DB_PATH=None, DATABASE_URL=None):
        manager = DatabaseManager()
        manager.initialize()
