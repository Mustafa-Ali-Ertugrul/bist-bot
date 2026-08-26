"""Database manager WAL and repository tests."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.db.database import DatabaseManager, _validate_table_name  # noqa: E402
from bist_bot.db.repositories.signals_repository import SignalsRepository  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


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
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
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
        "bist_bot.db.connection.create_engine", return_value=mock_engine
    ) as create_engine_mock:
        with patch("bist_bot.db.database.scoped_session", return_value=mock_session_factory):
            with patch.object(DatabaseManager, "initialize", return_value=None):
                manager = DatabaseManager(database_url="postgresql+psycopg2://user:pass@host/db")

    assert manager.get_journal_mode() == "n/a"
    create_engine_mock.assert_called_once()
    engine_url = create_engine_mock.call_args.args[0]
    engine_kwargs = create_engine_mock.call_args.kwargs
    assert engine_url == "postgresql+psycopg2://user:pass@host/db"
    assert engine_kwargs["pool_pre_ping"] is True
    assert engine_kwargs["pool_size"] == 10
    assert engine_kwargs["max_overflow"] == 20
    assert "connect_args" not in engine_kwargs


@pytest.mark.parametrize(
    "name,expected",
    [
        ("paper_trades", "paper_trades"),
        ("paper_trades_test", "paper_trades_test"),
        ("_paper_trades", "_paper_trades"),
        ("signals", "signals"),
        ("my_table_123", "my_table_123"),
    ],
)
def test_validate_table_name_valid(name, expected):
    assert _validate_table_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "paper_trades;DROP_TABLE",
        "paper-trades",
        "123paper_trades",
        "paper trades",
        "paper_trades\na",
        "paper_trades--comment",
    ],
)
def test_validate_table_name_invalid(name):
    with pytest.raises(ValueError):
        _validate_table_name(name)


def test_signals_day_query_survives_database_reinit(tmp_path):
    """Restart senaryosu: ayni SQLite dosyasi uzerinde ikinci DatabaseManager
    init'i sonrasi gun sorgusu calismaya devam etmeli.

    Eski migration ORM'in yazdigi space-separator degerleri 'T'ye cevirdigi
    icin ikinci init sonrasi gun araligi karsilastirmalari sessizce satir
    dusuruyordu; migration idempotent olmali ve ORM formatini bozmamali.
    """
    db_path = str(tmp_path / "restart.db")
    repo = SignalsRepository(manager=DatabaseManager(sqlite_path=db_path))
    repo.save_signal(
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=30.0,
            price=100.0,
            timestamp=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),  # 12:00 TR
        )
    )

    # Surec restart'i simule et: ayni dosyada migration yeniden calisir.
    repo2 = SignalsRepository(manager=DatabaseManager(sqlite_path=db_path))

    rows = repo2.get_signals_for_day(date(2026, 8, 20), tz=ZoneInfo("Europe/Istanbul"))
    assert [row["ticker"] for row in rows] == ["THYAO.IS"]
    assert repo2.get_latest_signal("THYAO.IS") is not None


def test_legacy_t_separator_timestamps_repaired_by_migration(tmp_path):
    """Legacy 'T' separatorlu satirlar re-init'te SQLAlchemy'nin space
    formatina normalize edilmeli ve gun sorgularinda bulunabilmeli."""
    db_path = str(tmp_path / "legacy.db")
    manager = DatabaseManager(sqlite_path=db_path)
    repo = SignalsRepository(manager=manager)
    repo.save_signal(
        Signal(
            ticker="GARAN.IS",
            signal_type=SignalType.WEAK_BUY,
            score=18.0,
            price=50.0,
            timestamp=datetime(2026, 8, 12, 10, 15, tzinfo=UTC),  # 13:15 TR
        )
    )

    # Legacy veriyi simule et: ORM'in yazdigi space formati raw SQL ile 'T'ye cevir.
    with manager.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE signals SET timestamp = "
                "substr(timestamp, 1, 10) || 'T' || substr(timestamp, 12)"
            )
        )

    # Re-init: _normalize_timestamp_columns 'T' -> space donusumu yapmali.
    repo2 = SignalsRepository(manager=DatabaseManager(sqlite_path=db_path))

    rows = repo2.get_signals_for_day(date(2026, 8, 12), tz=ZoneInfo("Europe/Istanbul"))
    assert [row["ticker"] for row in rows] == ["GARAN.IS"]
