"""Basic repository tests for signal persistence."""

from __future__ import annotations

from datetime import datetime

import pytest

from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.signal_models import Signal, SignalType


@pytest.fixture
def signals_repo(tmp_path):
    manager = DatabaseManager(sqlite_path=str(tmp_path / "signals_test.db"))
    return SignalsRepository(manager=manager)


@pytest.fixture
def sample_signal():
    return Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        reasons=["RSI low", "MACD bullish"],
        stop_loss=95.0,
        target_price=110.0,
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )


def test_duplicate_signal_is_not_saved_twice(signals_repo, sample_signal):
    signals_repo.save_signal(sample_signal)
    signals_repo.save_signal(sample_signal)

    rows = signals_repo.get_signals(limit=10, ticker="THYAO.IS")

    assert len(rows) == 1


def test_saved_signal_can_be_read_back(signals_repo, sample_signal):
    signals_repo.save_signal(sample_signal)

    latest = signals_repo.get_latest_signal("THYAO.IS")

    assert latest is not None
    assert latest["ticker"] == "THYAO.IS"
    assert latest["signal_type"] == SignalType.BUY.value


def test_empty_db_query_does_not_crash(signals_repo):
    assert signals_repo.get_latest_signal("MISSING.IS") is None
    assert signals_repo.get_signals(limit=10, ticker="MISSING.IS") == []
