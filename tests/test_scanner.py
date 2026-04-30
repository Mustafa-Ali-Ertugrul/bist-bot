"""Scanner orchestration tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

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
        settings=settings.replace(PAPER_MODE=True),
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
    db.save_scan_log.assert_called_once_with(1, 1, 1, 0, 1)


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
        settings=settings.replace(PAPER_MODE=False),
        paper_trade_service=paper_trade_service,
    )

    service.scan_once()

    paper_trade_service.queue_actionable_signals.assert_not_called()
    paper_trade_service.update_open_trades.assert_not_called()
    assert service.last_side_effects["paper_trades_queued"] is False


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


def test_scan_once_blocks_when_circuit_breaker_open():
    """When circuit breaker is open, scan returns [] without fetching data."""
    fetcher = MagicMock()
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    circuit_breaker = MagicMock()
    circuit_breaker.allow_request.return_value = False

    service = ScanService(fetcher, engine, notifier, db, circuit_breaker=circuit_breaker)
    result = service.scan_once()

    assert result == []
    fetcher.fetch_multi_timeframe_all.assert_not_called()
    engine.scan_all.assert_not_called()
    db.save_signals.assert_not_called()


def test_scan_once_records_circuit_breaker_success():
    """Successful scan calls circuit_breaker.record_success()."""
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    circuit_breaker = MagicMock()
    circuit_breaker.allow_request.return_value = True
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0)
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    service = ScanService(fetcher, engine, notifier, db, circuit_breaker=circuit_breaker)
    service.scan_once()

    circuit_breaker.record_success.assert_called_once()
    circuit_breaker.record_error.assert_not_called()


def test_scan_once_records_circuit_breaker_error():
    """Failed scan calls circuit_breaker.record_error() before re-raising."""
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.side_effect = RuntimeError("provider down")
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    circuit_breaker = MagicMock()
    circuit_breaker.allow_request.return_value = True

    service = ScanService(fetcher, engine, notifier, db, circuit_breaker=circuit_breaker)

    with pytest.raises(RuntimeError, match="provider down"):
        service.scan_once()

    circuit_breaker.record_error.assert_called_once()
    circuit_breaker.record_success.assert_not_called()


def test_scan_once_persists_all_signals_including_hold():
    """Verify that HOLD/BEKLE signals are persisted to DB, not filtered out."""
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "ASELS.IS": {"trigger": object(), "trend": object()},
        "THYAO.IS": {"trigger": object(), "trend": object()},
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    signal_change_service = MagicMock()
    execution_service = MagicMock()
    paper_trade_service = MagicMock()
    notification_service = MagicMock()

    hold_signal = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.HOLD,
        score=3,
        price=150.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0),
    )
    buy_signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25,
        price=100.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0),
    )
    engine.scan_all.return_value = [hold_signal, buy_signal]
    engine.get_actionable_signals.return_value = [buy_signal]

    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        signal_change_service=signal_change_service,
        execution_service=execution_service,
        paper_trade_service=paper_trade_service,
        notification_service=notification_service,
    )
    result = service.scan_once()

    assert len(result) == 2
    saved_signals = db.save_signals.call_args[0][0]
    assert len(saved_signals) == 2
    saved_tickers = {s.ticker for s in saved_signals}
    assert "ASELS.IS" in saved_tickers
    assert "THYAO.IS" in saved_tickers
    execution_service.auto_execute_signals.assert_called_once()
    executed = execution_service.auto_execute_signals.call_args[0][0]
    assert len(executed) == 1
    assert executed[0].ticker == "THYAO.IS"
