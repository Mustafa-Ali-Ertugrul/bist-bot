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


def test_signal_ttl_minutes_default():
    import os

    from bist_bot.config.settings import settings

    expected = int(os.environ.get("SIGNAL_TTL_MINUTES", 60))
    assert settings.SIGNAL_TTL_MINUTES == expected


def test_telegram_min_score_default():
    import os

    from bist_bot.config.settings import settings

    expected = int(os.environ.get("TELEGRAM_MIN_SCORE", os.environ.get("STRONG_BUY_THRESHOLD", 48)))
    assert settings.TELEGRAM_MIN_SCORE == expected


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


def test_naive_timestamp_raises_value_error():
    from bist_bot.strategy.signal_models import ensure_utc

    naive_ts = datetime(2025, 1, 1, 10, 0, 0)
    with pytest.raises(ValueError, match="Naive datetime"):
        ensure_utc(naive_ts)


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
    manager = DatabaseManager(database_url=f"sqlite:///{temp_path}", sqlite_path=temp_path)
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
    from types import SimpleNamespace

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

    service = NotificationDispatchService(
        FakeNotifier(),
        settings=SimpleNamespace(TELEGRAM_GROUP_CHAT_ID=""),
        sleeper=lambda _: None,
    )
    service.notify_scan_results(actionable, actionable, 100)

    assert len(sent) == 1
    assert sent[0].ticker == "FRESH.IS"


def test_notification_sends_positive_scores_only():
    from types import SimpleNamespace

    from bist_bot.services.notification_service import NotificationDispatchService

    sent = []

    class FakeNotifier:
        def send_scan_summary(self, signals, total):
            pass

        def send_signal(self, signal):
            sent.append(signal)

    actionable = [
        Signal(ticker="LOW.IS", signal_type=SignalType.BUY, score=39.0, price=100.0),
        Signal(ticker="MIN.IS", signal_type=SignalType.BUY, score=40.0, price=100.0),
        Signal(ticker="SELL.IS", signal_type=SignalType.STRONG_SELL, score=-60.0, price=100.0),
    ]

    service = NotificationDispatchService(
        FakeNotifier(),
        settings=SimpleNamespace(TELEGRAM_GROUP_CHAT_ID=""),
        sleeper=lambda _: None,
    )
    service.notify_scan_results(actionable, actionable, 100)

    assert [signal.ticker for signal in sent] == ["LOW.IS", "MIN.IS"]
