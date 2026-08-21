"""Signal change service tests."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.services.signal_change_service import SignalChangeService  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402

PREV_TIMESTAMP = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat()
NEW_TIMESTAMP = datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC)

GATE_PARAMS = StrategyParams(buy_threshold=25.0, sell_threshold=-25.0)


def build_previous_record(
    signal_type: SignalType, score: float, *, timestamp: str | None = None
) -> dict:
    return {
        "ticker": "THYAO.IS",
        "signal_type": signal_type.value,
        "score": score,
        "price": 100.0,
        "stop_loss": 95.0,
        "target_price": 110.0,
        "position_size": 5,
        "confidence": "ORTA",
        "timestamp": timestamp if timestamp is not None else PREV_TIMESTAMP,
    }


def run_signal_change(
    previous: dict | None,
    new_signal: Signal,
    *,
    params: StrategyParams | None = None,
    min_score_delta: float | None = 15.0,
) -> tuple[MagicMock, MagicMock, SignalChangeService]:
    db = MagicMock()
    db.get_latest_signal.return_value = previous
    notifier = MagicMock()
    sleeper = MagicMock()
    service = SignalChangeService(
        db,
        notifier,
        sleeper=sleeper,
        params=params or GATE_PARAMS,
        min_score_delta=min_score_delta,
    )
    service.check_signal_changes([new_signal])
    return notifier, sleeper, service


def test_gate_notifies_when_old_signal_actionable():
    """BUY(26) -> WEAK_BUY(18): only old actionable, delta 8 < 15 -> notify."""
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.BUY, 26.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_BUY,
            score=18.0,
            price=101.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_gate_notifies_when_new_signal_actionable():
    """WEAK_BUY(15) -> BUY(26): only new actionable, delta 11 < 15 -> notify."""
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.WEAK_BUY, 15.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=26.0,
            price=101.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_gate_notifies_when_both_signals_actionable():
    """BUY(26) -> SELL(-30): both actionable -> notify."""
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.BUY, 26.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.SELL,
            score=-30.0,
            price=99.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_gate_notifies_on_score_delta_when_neither_actionable():
    """WEAK_BUY(5) -> WEAK_SELL(-14): non-actionable but delta 19 >= 15 -> notify."""
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.WEAK_BUY, 5.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-14.0,
            price=100.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_gate_boundary_delta_is_inclusive():
    """Delta exactly equal to the threshold must notify (>=, not >)."""
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.WEAK_BUY, 5.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-10.0,
            price=100.0,
            timestamp=NEW_TIMESTAMP,
        ),
        min_score_delta=15.0,
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_gate_suppresses_non_actionable_small_change(monkeypatch):
    """WEAK_BUY(5) -> WEAK_SELL(-9): non-actionable, delta 14 < 15 -> suppress, but log."""
    from bist_bot.services import signal_change_service as module

    fake_logger = MagicMock()
    monkeypatch.setattr(module, "logger", fake_logger)

    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.WEAK_BUY, 5.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-9.0,
            price=100.0,
            timestamp=NEW_TIMESTAMP,
        ),
        min_score_delta=15.0,
    )
    notifier.send_signal_change.assert_not_called()
    sleeper.assert_not_called()

    fake_logger.info.assert_called_once()
    _, kwargs = fake_logger.info.call_args
    assert kwargs["notified"] is False
    assert kwargs["suppressed"] is True
    assert kwargs["gate"] == "suppressed_non_actionable"
    assert "14.00" in kwargs["suppress_reason"]


def test_gate_legacy_zero_delta_notifies_every_change():
    """min_score_delta=0 restores legacy behaviour: any signal-type change notifies."""
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.WEAK_BUY, 5.0),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_SELL,
            score=0.0,
            price=100.0,
            timestamp=NEW_TIMESTAMP,
        ),
        min_score_delta=0.0,
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_gate_treats_missing_score_as_zero():
    """Missing previous score is normalized to 0.0; delta is measured against 0."""
    previous = build_previous_record(SignalType.WEAK_BUY, 0.0)
    previous["score"] = None
    notifier, sleeper, _ = run_signal_change(
        previous,
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-16.0,  # delta 16 >= 15
            price=99.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_first_seen_signal_stays_silent(monkeypatch):
    """No previous signal: no notification, but audited with gate=first_signal."""
    from bist_bot.services import signal_change_service as module

    fake_logger = MagicMock()
    monkeypatch.setattr(module, "logger", fake_logger)

    notifier, sleeper, _ = run_signal_change(
        None,
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=30.0,
            price=100.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_not_called()
    sleeper.assert_not_called()

    fake_logger.debug.assert_called_once()
    args, kwargs = fake_logger.debug.call_args
    assert args[0] == "signal_changed"
    assert kwargs["gate"] == "first_signal"
    assert kwargs["notified"] is False


def test_malformed_previous_timestamp_skips_transition():
    notifier, sleeper, _ = run_signal_change(
        build_previous_record(SignalType.BUY, 26.0, timestamp="not-a-date"),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.SELL,
            score=-30.0,
            price=99.0,
            timestamp=NEW_TIMESTAMP,
        ),
    )
    notifier.send_signal_change.assert_not_called()
    sleeper.assert_not_called()


def test_sleeper_runs_only_for_notified_changes():
    """One suppressed + one notified change -> exactly one send and one sleep."""
    db = MagicMock()
    db.get_latest_signal.side_effect = [
        build_previous_record(SignalType.WEAK_BUY, 5.0),
        build_previous_record(SignalType.BUY, 26.0),
    ]
    notifier = MagicMock()
    sleeper = MagicMock()
    service = SignalChangeService(
        db,
        notifier,
        sleeper=sleeper,
        params=GATE_PARAMS,
        min_score_delta=15.0,
    )
    suppressed = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.WEAK_SELL,
        score=-9.0,  # delta 14 < 15, no actionable side
        price=100.0,
        timestamp=NEW_TIMESTAMP,
    )
    notified = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.SELL,
        score=-30.0,  # actionable
        price=99.0,
        timestamp=NEW_TIMESTAMP,
    )

    service.check_signal_changes([suppressed, notified])

    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_signal_change_service_sends_notification_on_change():
    db = MagicMock()
    notifier = MagicMock()
    sleeper = MagicMock()
    db.get_latest_signal.return_value = {
        "ticker": "THYAO.IS",
        "signal_type": SignalType.BUY.value,
        "score": 20,
        "price": 100.0,
        "stop_loss": 95.0,
        "target_price": 110.0,
        "position_size": 5,
        "confidence": "ORTA",
        "timestamp": datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat(),
    }
    service = SignalChangeService(db, notifier, sleeper=sleeper)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.SELL,
        score=-20,
        price=99.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
    )

    service.check_signal_changes([signal])

    notifier.send_signal_change.assert_called_once()
    sleeper.assert_called_once_with(1)


def test_signal_change_service_skips_when_signal_is_same():
    db = MagicMock()
    notifier = MagicMock()
    sleeper = MagicMock()
    db.get_latest_signal.return_value = {
        "ticker": "THYAO.IS",
        "signal_type": SignalType.BUY.value,
        "score": 20,
        "price": 100.0,
        "timestamp": datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat(),
    }
    service = SignalChangeService(db, notifier, sleeper=sleeper)
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=101.0)

    service.check_signal_changes([signal])

    notifier.send_signal_change.assert_not_called()
    sleeper.assert_not_called()
