"""Database manager WAL and repository tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from db.database import DatabaseManager
from db.repositories.signals_repository import SignalsRepository
from signal_models import Signal, SignalType


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
