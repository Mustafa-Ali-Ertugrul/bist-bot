"""Scanner orchestration tests."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
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
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 2,
        "by_reason": [{"reason_code": "mtf_confluence_blocked", "count": 2}],
        "by_stage": [{"stage": "mtf", "count": 2}],
        "scan_id": "scan-test123",
    }
    signal_change_service = MagicMock()
    execution_service = MagicMock()
    paper_trade_service = MagicMock()
    notification_service = MagicMock()
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=75,
        price=100.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
    )
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        settings=settings.replace(PAPER_MODE=True, AGENT_ENABLED=False),
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
    paper_trade_service.update_open_trades.assert_called_once_with(signals=[signal])
    notification_service.notify_scan_results.assert_called_once_with([signal], [signal], 1)
    db.save_signals.assert_called_once_with([signal])
    db.save_scan_log.assert_called_once_with(
        1,
        1,
        1,
        0,
        1,
        scan_id="scan-test123",
        rejection_breakdown={
            "total_rejections": 2,
            "by_reason": [{"reason_code": "mtf_confluence_blocked", "count": 2}],
            "by_stage": [{"stage": "mtf", "count": 2}],
            "scan_id": "scan-test123",
        },
    )


def test_scan_once_skips_paper_trade_updates_when_disabled():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-empty",
    }
    paper_trade_service = MagicMock()
    signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0)
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        settings=settings.replace(PAPER_MODE=False, AGENT_ENABLED=False),
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
    paper_trade_service.update_open_trades.assert_called_once_with(signals=None)


def test_scan_once_force_refresh_uses_selective_invalidation():
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-force",
    }
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
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-success",
    }
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
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 1,
        "by_reason": [{"reason_code": "insufficient_history", "count": 1}],
        "by_stage": [{"stage": "data", "count": 1}],
        "scan_id": "scan-hold",
    }
    signal_change_service = MagicMock()
    execution_service = MagicMock()
    paper_trade_service = MagicMock()
    notification_service = MagicMock()

    hold_signal = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.HOLD,
        score=3,
        price=150.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
    )
    buy_signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=25,
        price=100.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
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
        settings=settings.replace(AGENT_ENABLED=False),
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


def test_scan_once_skips_auto_execute_when_agent_enabled():
    """BUG-5: AGENT_ENABLED=True → ScanService auto_execute MUST be skipped."""
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-agent",
    }
    execution_service = MagicMock()
    notification_service = MagicMock()
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=80,
        price=100.0,
        timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
    )
    engine.scan_all.return_value = [signal]
    engine.get_actionable_signals.return_value = [signal]

    mock_settings = MagicMock()
    mock_settings.WATCHLIST = ["THYAO.IS"]
    mock_settings.WATCHLIST_SOURCE = "test"
    mock_settings.PAPER_MODE = False
    mock_settings.AGENT_ENABLED = True
    mock_settings.agent = MagicMock()
    mock_settings.agent.AGENT_ENABLED = True

    service = ScanService(
        fetcher,
        engine,
        notifier,
        db,
        settings=mock_settings,
        execution_service=execution_service,
        notification_service=notification_service,
    )

    result = service.scan_once()

    assert result == [signal]
    execution_service.auto_execute_signals.assert_not_called()


def test_scan_once_dedups_sell_family_per_ticker_per_day():
    """#1: Max 1 persisted SAT per ticker per day.

    - Existing SAT for XU100.IS today (from DB) must suppress a new SAT persist.
    - Two SAT signals for GARAN.IS in one scan batch must collapse to 1 persisted.
    - Non-SAT signals (BUY / HOLD) must pass through unfiltered.
    """
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()},
        "GARAN.IS": {"trigger": object(), "trend": object()},
        "XU100.IS": {"trigger": object(), "trend": object()},
        "ASELS.IS": {"trigger": object(), "trend": object()},
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    db.get_signal_tickers_for_day.return_value = {"XU100.IS"}
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-sat-dedup",
    }

    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    sat_g1 = Signal(
        ticker="GARAN.IS",
        signal_type=SignalType.SELL,
        score=-20,
        price=80.0,
        timestamp=now,
    )
    sat_g2 = Signal(
        ticker="GARAN.IS",
        signal_type=SignalType.STRONG_SELL,
        score=-35,
        price=80.5,
        timestamp=now,
    )
    sat_x = Signal(
        ticker="XU100.IS",
        signal_type=SignalType.SELL,
        score=-25,
        price=9000.0,
        timestamp=now,
    )
    sat_t = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.WEAK_SELL,
        score=-15,
        price=100.0,
        timestamp=now,
    )
    buy_a = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=150.0,
        timestamp=now,
    )
    engine.scan_all.return_value = [sat_g1, sat_g2, sat_x, sat_t, buy_a]
    engine.get_actionable_signals.return_value = [buy_a]

    service = ScanService(fetcher, engine, notifier, db)
    result = service.scan_once()

    # Full result list unchanged (notifications/outcomes see all signals)
    assert len(result) == 5

    # Persisted list: only 3 (one GARAN duplicate dropped; XU100 dropped by DB dedup).
    saved = db.save_signals.call_args[0][0]
    saved_tickers = [s.ticker for s in saved]
    assert len(saved) == 3
    assert saved_tickers.count("GARAN.IS") == 1
    assert "XU100.IS" not in saved_tickers
    assert "THYAO.IS" in saved_tickers
    assert "ASELS.IS" in saved_tickers


def test_scan_once_no_dedup_when_no_sells():
    """No sell-family in the scan -> repository dedup is a no-op."""
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-nosat",
    }
    buy = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=100.0,
        timestamp=datetime(2026, 8, 20, 11, 0, tzinfo=UTC),
    )
    engine.scan_all.return_value = [buy]
    engine.get_actionable_signals.return_value = [buy]

    service = ScanService(fetcher, engine, notifier, db)
    service.scan_once()

    # No sell signals -> repository helper never queried
    db.get_signal_tickers_for_day.assert_not_called()
    db.save_signals.assert_called_once_with([buy])


# ---------------------------------------------------------------------------
# AL-signal cooldown (per-ticker, time-based persistence dedup)
# ---------------------------------------------------------------------------


def _al_cooldown_scan_setup(db_recent: dict, scan_signals: list[Signal]):
    """Shared scaffolding for AL cooldown tests: mocked scan pipeline."""
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        s.ticker: {"trigger": object(), "trend": object()} for s in scan_signals
    }
    engine = MagicMock()
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    db.get_signal_tickers_for_day.return_value = set()
    # AL cooldown lookup: {ticker: last_signal_time}
    db.get_last_signal_times.return_value = db_recent
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-al-cooldown",
    }
    engine.scan_all.return_value = scan_signals
    engine.get_actionable_signals.return_value = [
        s for s in scan_signals if s.signal_type.is_buy and s.score >= 25
    ]
    service = ScanService(fetcher, engine, notifier, db)
    return service, db


def test_scan_once_dedups_al_signals_within_cooldown():
    """Ticker with a recent persisted buy signal (within 60 min) is suppressed."""
    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    recent_time = now - timedelta(minutes=15)  # inside the 60-min window
    buy_hal = Signal(
        ticker="HALKB.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=46.0,
        timestamp=now,
    )
    buy_ase = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.BUY,
        score=35,
        price=150.0,
        timestamp=now,
    )
    service, db = _al_cooldown_scan_setup(
        db_recent={"HALKB.IS": recent_time},
        scan_signals=[buy_hal, buy_ase],
    )
    result = service.scan_once()

    # Full list unchanged for notifications/outcomes
    assert len(result) == 2

    # Persisted: HALKB dropped (DB cooldown), ASELS kept
    saved = db.save_signals.call_args[0][0]
    saved_tickers = [s.ticker for s in saved]
    assert "HALKB.IS" not in saved_tickers
    assert "ASELS.IS" in saved_tickers


def test_scan_once_dedups_al_signals_within_same_batch():
    """Two AL signals for the same ticker in one batch collapse to one persist."""
    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    al_1 = Signal(
        ticker="TUPRS.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=390.0,
        timestamp=now,
    )
    al_2 = Signal(
        ticker="TUPRS.IS",
        signal_type=SignalType.STRONG_BUY,
        score=45,
        price=391.0,
        timestamp=now,
    )
    service, db = _al_cooldown_scan_setup(
        db_recent={},
        scan_signals=[al_1, al_2],
    )
    service.scan_once()

    saved = db.save_signals.call_args[0][0]
    saved_tickers = [s.ticker for s in saved]
    assert saved_tickers.count("TUPRS.IS") == 1


def test_scan_once_keeps_al_signal_when_cooldown_expired():
    """Ticker whose last buy signal is older than the window persists again.

    Note: get_last_signal_times filters by ``timestamp >= since`` in SQL, so a
    signal older than the cooldown window is never returned by the real repo.
    The mock here mirrors that contract (empty dict)."""
    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    buy = Signal(
        ticker="TUPRS.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=390.0,
        timestamp=now,
    )
    service, db = _al_cooldown_scan_setup(
        db_recent={},  # real repo would not return a 90-min-old signal
        scan_signals=[buy],
    )
    service.scan_once()

    saved = db.save_signals.call_args[0][0]
    saved_tickers = [s.ticker for s in saved]
    assert "TUPRS.IS" in saved_tickers


def test_scan_once_cooldown_does_not_touch_radar_or_sells():
    """RADAR (score < threshold) and SAT signals bypass the AL cooldown."""
    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    radar = Signal(
        ticker="HALKB.IS",
        signal_type=SignalType.BUY,
        score=15,  # below default buy_threshold 20 -> RADAR, not AL
        price=46.0,
        timestamp=now,
    )
    sat = Signal(
        ticker="TUPRS.IS",
        signal_type=SignalType.SELL,
        score=-20,
        price=390.0,
        timestamp=now,
    )
    service, db = _al_cooldown_scan_setup(
        db_recent={"HALKB.IS": now - timedelta(minutes=5)},
        scan_signals=[radar, sat],
    )
    service.scan_once()

    saved = db.save_signals.call_args[0][0]
    saved_tickers = [s.ticker for s in saved]
    # RADAR and SAT both persist — cooldown is AL-only.
    assert "HALKB.IS" in saved_tickers
    assert "TUPRS.IS" in saved_tickers
    # The cooldown lookup was never even queried (no AL candidates in batch).
    db.get_last_signal_times.assert_not_called()


def test_scan_once_cooldown_disabled_via_settings():
    """AL_SIGNAL_COOLDOWN_MINUTES=0 disables the filter entirely."""
    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    buy = Signal(
        ticker="HALKB.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=46.0,
        timestamp=now,
    )
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = {
        "HALKB.IS": {"trigger": object(), "trend": object()}
    }
    engine = MagicMock()
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "scan-cooldown-off",
    }
    engine.scan_all.return_value = [buy]
    engine.get_actionable_signals.return_value = [buy]
    notifier = MagicMock()
    db = MagicMock()
    db.get_latest_signal.return_value = None
    db.get_signal_tickers_for_day.return_value = set()

    settings_off = MagicMock()
    settings_off.AL_SIGNAL_COOLDOWN_MINUTES = 0
    # Other settings lookups the ScanService touches during scan_once:
    settings_off.WATCHLIST = ["HALKB.IS"]
    settings_off.WATCHLIST_SOURCE = "test"
    settings_off.MTF_TREND_PERIOD = "6mo"
    settings_off.MTF_TREND_INTERVAL = "1d"
    settings_off.MTF_TRIGGER_PERIOD = "1mo"
    settings_off.MTF_TRIGGER_INTERVAL = "15m"
    settings_off.SIGNAL_CHANGE_MIN_SCORE_DELTA = 15
    settings_off.AGENT_ENABLED = False
    settings_off.PAPER_MODE = False

    service = ScanService(fetcher, engine, notifier, db, settings=settings_off)
    service.scan_once()

    db.get_last_signal_times.assert_not_called()
    saved = db.save_signals.call_args[0][0]
    assert [s.ticker for s in saved] == ["HALKB.IS"]


def test_scan_once_al_cooldown_passes_buy_threshold_to_lookup():
    """The cooldown DB lookup must be filtered to actionable persists only
    (min_score = current buy threshold) so a RADAR/WEAK_BUY persist does not
    suppress the next AL signal for the same ticker."""
    now = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)
    buy = Signal(
        ticker="HALKB.IS",
        signal_type=SignalType.BUY,
        score=30,
        price=46.0,
        timestamp=now,
    )
    service, db = _al_cooldown_scan_setup(
        db_recent={},
        scan_signals=[buy],
    )
    service.scan_once()

    db.get_last_signal_times.assert_called_once()
    call_kwargs = db.get_last_signal_times.call_args.kwargs
    assert "min_score" in call_kwargs
    # StrategyParams default buy_threshold is 20.0 (env-overridable).
    assert call_kwargs["min_score"] >= 20.0
