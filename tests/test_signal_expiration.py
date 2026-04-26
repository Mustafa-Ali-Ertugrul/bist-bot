"""Tests for signal expiration lifecycle."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.signal_models import Signal, SignalType

# ── Settings defaults ──────────────────────────────────────────────────────


def test_signal_ttl_minutes_default_is_60():
    from bist_bot.config.settings import settings

    assert settings.SIGNAL_TTL_MINUTES == 60


def test_telegram_min_score_default_is_48():
    from bist_bot.config.settings import settings

    assert settings.TELEGRAM_MIN_SCORE == 48


# ── Signal is_expired behavior ─────────────────────────────────────────────


def test_is_expired_returns_false_when_expires_at_is_none():
    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        expires_at=None,
    )
    assert signal.is_expired() is False


def test_is_expired_returns_false_before_expires_at():
    future = datetime.now(UTC) + timedelta(hours=1)
    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        timestamp=datetime.now(UTC),
        expires_at=future,
    )
    assert signal.is_expired() is False


def test_is_expired_returns_true_at_expires_at():
    now = datetime.now(UTC)
    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        timestamp=now - timedelta(hours=1),
        expires_at=now,
    )
    assert signal.is_expired(now) is True


def test_is_expired_returns_true_after_expires_at():
    past = datetime.now(UTC) - timedelta(hours=1)
    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        timestamp=past - timedelta(hours=1),
        expires_at=past,
    )
    assert signal.is_expired() is True


def test_naive_aware_comparison_does_not_crash():
    naive_ts = datetime(2025, 1, 1, 10, 0, 0)
    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        timestamp=naive_ts,
    )
    # expires_at is set from naive timestamp, is_expired should not crash
    result = signal.is_expired()
    assert isinstance(result, bool)


def test_signal_auto_sets_expires_at():
    now = datetime.now(UTC)
    signal = Signal(
        ticker="TEST.IS",
        signal_type=SignalType.BUY,
        score=25.0,
        price=100.0,
        timestamp=now,
    )
    assert signal.expires_at is not None
    expected = now + timedelta(minutes=60)
    assert abs((signal.expires_at - expected).total_seconds()) < 1


# ── Database persistence ───────────────────────────────────────────────────


@pytest.fixture
def signals_repo():
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)
    manager = DatabaseManager(sqlite_path=temp_path)
    repo = SignalsRepository(manager=manager)
    try:
        yield repo
    finally:
        manager.session_factory.remove()
        if hasattr(manager, "engine"):
            manager.engine.dispose()
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_signal_record_supports_expires_at(signals_repo):
    now = datetime.now(UTC)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=50.0,
        price=100.0,
        timestamp=now,
    )
    signals_repo.save_signal(signal)
    rows = signals_repo.get_signals(limit=10, ticker="THYAO.IS")
    assert len(rows) == 1
    assert rows[0]["expires_at"] is not None
    assert rows[0]["is_expired"] is False


def test_expired_signal_marked_in_dict(signals_repo):
    past = datetime.now(UTC) - timedelta(hours=2)
    signal = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.SELL,
        score=-50.0,
        price=200.0,
        timestamp=past,
    )
    signals_repo.save_signal(signal)
    rows = signals_repo.get_signals(limit=10, ticker="ASELS.IS")
    assert len(rows) == 1
    assert rows[0]["is_expired"] is True


def test_null_expires_at_backward_compatible(signals_repo):
    from bist_bot.db.database import SignalRecord

    def _insert_null(session):
        session.add(
            SignalRecord(
                timestamp=datetime.now(UTC),
                created_at=datetime.now(UTC),
                ticker="GARAN.IS",
                signal_type="AL",
                score=30.0,
                price=150.0,
                reasons="",
                conditions="[]",
                expires_at=None,
            )
        )

    signals_repo.manager.run_session(_insert_null)
    rows = signals_repo.get_signals(limit=10, ticker="GARAN.IS")
    assert len(rows) == 1
    assert rows[0]["expires_at"] is None
    assert rows[0]["is_expired"] is False


# ── Notification filtering ─────────────────────────────────────────────────


def test_expired_signal_not_sent_to_notifier():
    from bist_bot.services.notification_service import NotificationDispatchService

    sent = []

    class FakeNotifier:
        def send_scan_summary(self, signals, total):
            pass

        def send_signal(self, signal):
            sent.append(signal)

    past = datetime.now(UTC) - timedelta(hours=2)
    actionable = [
        Signal(
            ticker="FRESH.IS",
            signal_type=SignalType.STRONG_BUY,
            score=50.0,
            price=100.0,
            timestamp=datetime.now(UTC),
        ),
        Signal(
            ticker="STALE.IS",
            signal_type=SignalType.STRONG_BUY,
            score=55.0,
            price=200.0,
            timestamp=past,
        ),
    ]

    service = NotificationDispatchService(FakeNotifier(), sleeper=lambda _: None)
    service.notify_scan_results(actionable, actionable, 100)

    assert len(sent) == 1
    assert sent[0].ticker == "FRESH.IS"
