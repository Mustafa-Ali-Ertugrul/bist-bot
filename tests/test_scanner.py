"""Scanner service tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import config  # noqa: E402
import scanner as scanner_module  # noqa: E402
from scanner import ScanService  # noqa: E402
from signal_models import Signal, SignalType  # noqa: E402


def test_scan_once_returns_empty_on_no_data():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {}
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    service = ScanService(fetcher, engine, notifier, db)

    assert service.scan_once() == []


def test_check_signal_changes_sends_notification_on_change(monkeypatch):
    monkeypatch.setattr(scanner_module, "sleep", lambda *_args, **_kwargs: None)

    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = {
        "ticker": "THYAO.IS",
        "signal_type": SignalType.BUY.value,
        "score": 20,
        "price": 100.0,
        "stop_loss": 95.0,
        "target_price": 110.0,
        "confidence": "ORTA",
        "timestamp": datetime(2025, 1, 1, 10, 0, 0).isoformat(),
    }
    service = ScanService(fetcher, engine, notifier, db)
    signals = [
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.SELL,
            score=-20,
            price=99.0,
            timestamp=datetime(2025, 1, 1, 11, 0, 0),
        )
    ]

    service._check_signal_changes(signals)

    notifier.send_signal_change.assert_called_once()


def test_update_paper_trades_skips_on_no_open_trades(monkeypatch):
    monkeypatch.setattr(config.settings, "PAPER_MODE", True, raising=False)

    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_open_paper_trades.return_value = []
    service = ScanService(fetcher, engine, notifier, db)

    service.update_paper_trades()

    fetcher.fetch_single.assert_not_called()
