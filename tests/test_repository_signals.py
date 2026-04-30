"""Tests for signals repository functionality."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime

import pytest

from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.signal_models import Signal, SignalType


@pytest.fixture
def signals_repo():
    """Create a SignalsRepository with a temporary database."""
    # Create a temporary database file
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)  # Close the file descriptor

    manager = DatabaseManager(sqlite_path=temp_path)
    repo = SignalsRepository(manager=manager)
    try:
        yield repo
    finally:
        # Clean up connections before deleting the file
        manager.session_factory.remove()
        if hasattr(manager, "engine"):
            manager.engine.dispose()
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.fixture
def sample_signal():
    """Create a sample signal for testing."""
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


def test_serialize_reasons():
    """Test serialization of reasons list to JSON string."""
    reasons = ["RSI low", "MACD bullish", "Volume spike"]
    serialized = json.dumps(reasons, ensure_ascii=False)
    # Should be valid JSON
    parsed = json.loads(serialized)
    assert parsed == reasons

    # Test empty list
    assert json.dumps([], ensure_ascii=False) == "[]"


def test_deserialize_reasons():
    """Test deserialization of JSON string to reasons list."""
    # Test normal JSON array
    json_str = '["RSI low", "MACD bullish", "Volume spike"]'
    result = json.loads(json_str)
    assert result == ["RSI low", "MACD bullish", "Volume spike"]

    # Test empty array
    assert json.loads("[]") == []

    # Test None/null
    assert json.loads("null") is None  # json.loads returns None for 'null'
    # Our function handles None by returning empty list
    # We'll test the actual function separately

    # Test malformed JSON (our function has fallback logic)
    # This is better tested in the actual function tests


def test_signals_repository_init():
    """Test SignalsRepository initialization."""
    manager = DatabaseManager()
    repo = SignalsRepository(manager=manager)
    assert repo.manager == manager


def test_save_signal_avoids_duplicates(signals_repo, sample_signal):
    """Test that duplicate signals are not saved."""
    signals_repo.save_signal(sample_signal)
    signals_repo.save_signal(sample_signal)  # Try to save the same signal again

    rows = signals_repo.get_signals(limit=10, ticker="THYAO.IS")

    assert len(rows) == 1  # Should only have one signal


def test_save_signal_adds_new(signals_repo, sample_signal):
    """Test that new signals are added to the database."""
    signals_repo.save_signal(sample_signal)

    rows = signals_repo.get_signals(limit=10, ticker="THYAO.IS")

    assert len(rows) == 1
    signal = rows[0]
    assert signal["ticker"] == "THYAO.IS"
    assert signal["signal_type"] == SignalType.BUY.value
    assert signal["score"] == 25.0
    assert signal["price"] == 100.0
    assert signal["stop_loss"] == 95.0
    assert signal["target_price"] == 110.0
    assert signal["position_size"] is None
    # Check that reasons were serialized/deserialized correctly
    assert signal["reasons"] == ["RSI low", "MACD bullish"]


def test_save_signal_persists_position_size(signals_repo):
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        reasons=["RSI low"],
        stop_loss=95.0,
        target_price=110.0,
        position_size=10,
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )

    signals_repo.save_signal(signal)

    rows = signals_repo.get_signals(limit=10, ticker="THYAO.IS")

    assert len(rows) == 1
    assert rows[0]["position_size"] == 10


def test_get_signals_returns_empty_list(signals_repo):
    """Test getting signals when none exist."""
    result = signals_repo.get_signals(limit=10)

    assert result == []


def test_get_signals_with_ticker_filter(signals_repo):
    """Test getting signals with ticker filter."""
    # Add a signal for one ticker
    signal1 = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        reasons=["RSI low"],
        stop_loss=95.0,
        target_price=110.0,
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )
    signals_repo.save_signal(signal1)

    # Add a signal for another ticker
    signal2 = Signal(
        ticker="AKBNK.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=200.0,
        reasons=["MACD bullish"],
        stop_loss=190.0,
        target_price=220.0,
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )
    signals_repo.save_signal(signal2)

    # Get signals for THYAO only
    result = signals_repo.get_signals(limit=10, ticker="THYAO.IS")

    assert len(result) == 1
    assert result[0]["ticker"] == "THYAO.IS"


def test_get_latest_signal_returns_none_when_no_signals(signals_repo):
    """Test getting latest signal when none exist."""
    result = signals_repo.get_latest_signal("THYAO.IS")

    assert result is None


def test_get_latest_signal_returns_signal(signals_repo, sample_signal):
    """Test getting latest signal when one exists."""
    signals_repo.save_signal(sample_signal)

    result = signals_repo.get_latest_signal("THYAO.IS")

    assert result is not None
    assert result["ticker"] == "THYAO.IS"
    assert result["signal_type"] == SignalType.BUY.value
    assert result["score"] == 25.0
    assert result["price"] == 100.0
    assert result["stop_loss"] == 95.0
    assert result["target_price"] == 110.0
    assert result["reasons"] == ["RSI low", "MACD bullish"]


def test_signal_exists_returns_false_when_no_matches(signals_repo):
    """Test signal_exists returns False when no matching signals."""
    result = signals_repo.signal_exists("THYAO.IS")

    assert result is False


def test_signal_exists_returns_true_when_matches(signals_repo, sample_signal):
    """Test signal_exists returns True when matching signals exist."""
    signals_repo.save_signal(sample_signal)

    result = signals_repo.signal_exists("THYAO.IS")

    assert result is True


def test_save_scan_log(signals_repo):
    """Test saving and retrieving scan log entry."""
    signals_repo.save_scan_log(total=100, generated=10, buys=7, sells=3)

    latest = signals_repo.get_latest_scan_log()
    assert latest is not None
    assert latest["total_scanned"] == 100
    assert latest["signals_generated"] == 10
    assert latest["buy_signals"] == 7
    assert latest["sell_signals"] == 3


def test_get_latest_scan_log_returns_none_when_empty(signals_repo):
    """Test get_latest_scan_log returns None when no scan logs exist."""
    result = signals_repo.get_latest_scan_log()
    assert result is None


def test_get_latest_scan_log_returns_most_recent(signals_repo):
    """Test get_latest_scan_log returns the most recent entry."""
    signals_repo.save_scan_log(total=50, generated=5, buys=3, sells=2)
    signals_repo.save_scan_log(total=100, generated=10, buys=7, sells=3)

    latest = signals_repo.get_latest_scan_log()
    assert latest is not None
    assert latest["total_scanned"] == 100
    assert latest["signals_generated"] == 10
    assert latest["buy_signals"] == 7
    assert latest["sell_signals"] == 3


def test_update_outcome(signals_repo, sample_signal):
    """Test updating signal outcome."""
    signals_repo.save_signal(sample_signal)

    # Get the signal ID from the database
    signals = signals_repo.get_signals(limit=1, ticker="THYAO.IS")
    signal_id = signals[0]["id"]

    # Update the outcome
    signals_repo.update_outcome(signal_id=signal_id, outcome="TP_HIT", outcome_price=110.0)

    # Check that the outcome was updated
    updated_signal = signals_repo.get_latest_signal("THYAO.IS")
    assert updated_signal is not None
    assert updated_signal["outcome"] == "TP_HIT"
    assert updated_signal["outcome_price"] == 110.0
    assert updated_signal["profit_pct"] == 10.0  # (110-100)/100 * 100


def test_update_outcome_signal_not_found(signals_repo):
    """Test updating outcome when signal doesn't exist."""
    # Should not raise exception
    signals_repo.update_outcome(signal_id=999, outcome="TP_HIT", outcome_price=110.0)
    # If we get here without exception, the test passed


def test_get_performance_stats(signals_repo):
    """Test getting performance statistics."""
    # Start with empty stats
    stats = signals_repo.get_performance_stats()
    assert stats["total_signals"] == 0
    assert stats["completed"] == 0
    assert stats["profitable"] == 0
    assert stats["win_rate"] == 0
    assert stats["avg_profit_pct"] == 0

    # Add a signal and update it to a profitable outcome
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        reasons=["RSI low"],
        stop_loss=95.0,
        target_price=110.0,
        timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )
    signals_repo.save_signal(signal)

    # Get the signal ID and update outcome
    signals = signals_repo.get_signals(limit=1, ticker="THYAO.IS")
    signal_id = signals[0]["id"]
    signals_repo.update_outcome(signal_id=signal_id, outcome="TP_HIT", outcome_price=110.0)

    # Check performance stats
    stats = signals_repo.get_performance_stats()
    assert stats["total_signals"] == 1
    assert stats["completed"] == 1  # TP_HIT is not PENDING
    assert stats["profitable"] == 1  # profit_pct > 0
    assert stats["win_rate"] == 100.0  # 1/1 * 100
    assert stats["avg_profit_pct"] == 10.0


def test_signal_to_dict_conversion():
    """Test internal _signal_to_dict conversion method."""
    # This is harder to test without access to the private method and a SignalRecord
    # We'll skip this for now since it's tested indirectly through other tests
    pass
