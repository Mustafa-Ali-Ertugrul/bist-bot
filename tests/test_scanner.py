"""Scanner orchestration tests."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.scanner import ScanService  # noqa: E402
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402


def test_scan_once_returns_empty_on_no_data():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {}
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    service = ScanService(fetcher, engine, notifier, db)

    assert service.scan_once() == []


def test_scan_once_orchestrates_side_effect_services():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    signal_change_service = MagicMock()
    execution_service = MagicMock()
    paper_trade_service = MagicMock()
    notification_service = MagicMock()
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=75,
        price=100.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0),
    )
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        settings=replace(settings, PAPER_MODE=True),
        signal_change_service=signal_change_service,
        execution_service=execution_service,
        paper_trade_service=paper_trade_service,
        notification_service=notification_service,
    )

    result = service.scan_once()

    assert result == [signal]
    signal_change_service.check_signal_changes.assert_called_once_with([signal])
    execution_service.auto_execute_signals.assert_called_once_with([signal])
    paper_trade_service.queue_actionable_signals.assert_called_once_with([signal])
    paper_trade_service.update_open_trades.assert_called_once_with()
    notification_service.notify_scan_results.assert_called_once_with([signal], [signal], 1)
    db.save_signals.assert_called_once_with([signal])
    db.save_scan_log.assert_called_once_with(1, 1, 1, 0)


def test_scan_once_skips_paper_trade_updates_when_disabled():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    paper_trade_service = MagicMock()
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0)
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        settings=replace(settings, PAPER_MODE=False),
        paper_trade_service=paper_trade_service,
    )

    service.scan_once()

    paper_trade_service.queue_actionable_signals.assert_called_once_with([signal])
    paper_trade_service.update_open_trades.assert_not_called()


def test_scan_service_backwards_compatible_wrappers_delegate():
    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    signal_change_service = MagicMock()
    execution_service = MagicMock()
    paper_trade_service = MagicMock()
    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        signal_change_service=signal_change_service,
        execution_service=execution_service,
        paper_trade_service=paper_trade_service,
    )
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.STRONG_BUY, score=80, price=100.0)

    service._check_signal_changes([signal])
    service._auto_execute_signals([signal])
    service.update_paper_trades()

    signal_change_service.check_signal_changes.assert_called_once_with([signal])
    execution_service.auto_execute_signals.assert_called_once_with([signal])
    paper_trade_service.update_open_trades.assert_called_once_with()


def test_scan_once_force_refresh_uses_selective_invalidation():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0)
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    service = ScanService(fetcher, engine, notifier, db)

    service.scan_once(force_refresh=True)

    fetcher.clear_cache.assert_any_call(scope="intraday_fetch")
    fetcher.clear_cache.assert_any_call(scope="analysis")
    fetcher.fetch_multi_timeframe_all.assert_called_once()
    assert fetcher.fetch_multi_timeframe_all.call_args.kwargs["force_refresh"] is True
