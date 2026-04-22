"""Signal change service tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.services.signal_change_service import SignalChangeService  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


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
        "timestamp": datetime(2025, 1, 1, 10, 0, 0).isoformat(),
    }
    service = SignalChangeService(db, notifier, sleeper=sleeper)
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.SELL,
        score=-20,
        price=99.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0),
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
        "timestamp": datetime(2025, 1, 1, 10, 0, 0).isoformat(),
    }
    service = SignalChangeService(db, notifier, sleeper=sleeper)
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=101.0)

    service.check_signal_changes([signal])

    notifier.send_signal_change.assert_not_called()
    sleeper.assert_not_called()
