"""Observation-only shadow trade logging tests."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.scanner import ScanService
from bist_bot.services.execution_service import ExecutionService
from bist_bot.services.shadow_trade_service import CSV_FIELDS, ShadowTradeService
from bist_bot.strategy.signal_models import Signal, SignalType

ROBUST = "THYAO.IS"
NON_ROBUST = "TAVHL.IS"
ENTRY_TIME = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


def _settings(**overrides):
    values = {
        "SHADOW_ENABLED": True,
        "SHADOW_HOLDING_DAYS": 5,
        "SHADOW_ONLY_ROBUST": True,
        "INITIAL_CAPITAL": 100_000.0,
        "MAX_TOTAL_RISK_PCT": 2.0,
        "AUTO_EXECUTE": False,
    }
    values.update(overrides)
    return settings.replace(**values)


def _signal(
    ticker: str = ROBUST,
    *,
    score: float = 15.0,
    signal_type: SignalType = SignalType.RADAR,
    price: float = 100.0,
) -> Signal:
    return Signal(
        ticker=ticker,
        signal_type=signal_type,
        score=score,
        price=price,
        stop_loss=95.0,
        target_price=110.0,
        agreement_ratio=0.5,
        reasons=["momentum", "volume"],
        timestamp=ENTRY_TIME,
    )


def _service(tmp_path, **settings_overrides) -> ShadowTradeService:
    return ShadowTradeService(
        settings=_settings(**settings_overrides),
        results_dir=tmp_path,
        robust_tickers={ROBUST},
    )


def _market_close(price: float):
    return {ROBUST: {"trigger": pd.DataFrame({"Close": [price]})}}


def test_radar_robust_creates_entry_without_broker_call(tmp_path):
    shadow = _service(tmp_path)
    broker = MagicMock()
    db = MagicMock()
    execution = ExecutionService(db, broker=broker, settings=_settings())
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = _market_close(100.0)
    engine = MagicMock()
    radar = _signal()
    engine.scan_all.return_value = [radar]
    engine.get_actionable_signals.return_value = []
    engine.get_last_rejection_breakdown.return_value = {}

    scanner = ScanService(
        fetcher,
        engine,
        MagicMock(),
        db,
        settings=_settings(WATCHLIST=[ROBUST]),
        execution_service=execution,
        shadow_trade_service=shadow,
        signal_change_service=MagicMock(),
        paper_trade_service=MagicMock(),
        notification_service=MagicMock(),
    )
    scanner.scan_once()

    open_rows = json.loads(shadow.open_path.read_text(encoding="utf-8"))
    assert list(open_rows) == [ROBUST]
    broker.submit_order.assert_not_called()
    broker.place_order.assert_not_called()
    db.create_order.assert_not_called()


def test_actionable_signal_is_not_shadowed(tmp_path):
    shadow = _service(tmp_path)
    actionable = _signal(score=25, signal_type=SignalType.BUY)
    fetcher = MagicMock()
    fetcher.fetch_multi_timeframe_all.return_value = _market_close(100.0)
    engine = MagicMock()
    engine.scan_all.return_value = [actionable]
    engine.get_actionable_signals.return_value = [actionable]
    engine.get_last_rejection_breakdown.return_value = {}
    execution = MagicMock()

    scanner = ScanService(
        fetcher,
        engine,
        MagicMock(),
        MagicMock(),
        settings=_settings(WATCHLIST=[ROBUST]),
        execution_service=execution,
        shadow_trade_service=shadow,
        signal_change_service=MagicMock(),
        paper_trade_service=MagicMock(),
        notification_service=MagicMock(),
    )
    scanner.scan_once()

    execution.auto_execute_signals.assert_called_once_with([actionable])
    assert not shadow.open_path.exists()
    assert not shadow.csv_path.exists()


def test_non_robust_radar_is_not_shadowed(tmp_path):
    service = _service(tmp_path)

    service.process_scan([_signal(ticker=NON_ROBUST)])

    assert not service.open_path.exists()


def test_subthreshold_weak_buy_is_observed_as_radar(tmp_path):
    service = _service(tmp_path)

    service.process_scan([_signal(score=15, signal_type=SignalType.WEAK_BUY)])

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert list(rows) == [ROBUST]


def test_below_min_score_is_rejected(tmp_path):
    """Signals below SHADOW_MIN_SCORE must not be shadowed (deep-radar noise)."""
    service = _service(tmp_path)

    service.process_scan([_signal(score=10, signal_type=SignalType.WEAK_BUY)])

    assert not service.open_path.exists()


def test_at_min_score_boundary_is_accepted(tmp_path):
    """Signals at exactly SHADOW_MIN_SCORE pass the floor filter."""
    service = _service(tmp_path)

    service.process_scan([_signal(score=15, signal_type=SignalType.WEAK_BUY)])

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert list(rows) == [ROBUST]


def test_custom_min_score_override(tmp_path):
    """Lowering SHADOW_MIN_SCORE via override allows lower-score shadow entries."""
    service = _service(tmp_path, SHADOW_MIN_SCORE=5)

    service.process_scan([_signal(score=10, signal_type=SignalType.WEAK_BUY)])

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert list(rows) == [ROBUST]


def test_stop_cooldown_blocks_reopening(tmp_path):
    """A ticker that recently stopped must not be reopened within COOLDOWN_DAYS."""
    service = _service(tmp_path, SHADOW_COOLDOWN_DAYS=3)
    service.process_scan([_signal()], now=ENTRY_TIME)
    # stop-hit close
    service.process_scan([], _market_close(94.0), now=ENTRY_TIME + timedelta(hours=1))
    # Signal comes again within cooldown window
    service.process_scan([_signal()], now=ENTRY_TIME + timedelta(hours=2))

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert rows == {}, "ticker must remain in cooldown, no new shadow position allowed"


def test_cooldown_expires_after_window(tmp_path):
    """After COOLDOWN_DAYS the ticker becomes eligible again."""
    service = _service(tmp_path, SHADOW_COOLDOWN_DAYS=3)
    service.process_scan([_signal()], now=ENTRY_TIME)
    service.process_scan([], _market_close(94.0), now=ENTRY_TIME + timedelta(hours=1))
    # 4 days later: cooldown expired, new entry allowed
    service.process_scan([_signal()], now=ENTRY_TIME + timedelta(days=4))

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert list(rows) == [ROBUST], "ticker should reopen after cooldown expires"


def test_target_close_does_not_trigger_cooldown(tmp_path):
    """Cooldown only applies to stop hits, not target (profitable exits)."""
    service = _service(tmp_path, SHADOW_COOLDOWN_DAYS=3)
    service.process_scan([_signal()], now=ENTRY_TIME)
    # target-hit close
    service.process_scan([], _market_close(111.0), now=ENTRY_TIME + timedelta(hours=1))
    # Immediate reopen should be allowed since cooldown only covers stops
    service.process_scan([_signal()], now=ENTRY_TIME + timedelta(hours=2))

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert list(rows) == [ROBUST], "target-hit must not block reopening"


def test_cooldown_disabled_when_zero(tmp_path):
    """SHADOW_COOLDOWN_DAYS=0 disables cooldown entirely."""
    service = _service(tmp_path, SHADOW_COOLDOWN_DAYS=0)
    service.process_scan([_signal()], now=ENTRY_TIME)
    service.process_scan([], _market_close(94.0), now=ENTRY_TIME + timedelta(hours=1))
    # No cooldown: immediate reopen allowed
    service.process_scan([_signal()], now=ENTRY_TIME + timedelta(hours=2))

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert list(rows) == [ROBUST], "cooldown=0 must allow immediate reopening"


def test_same_scan_closed_ticker_not_reopened(tmp_path):
    """A ticker closed within the same scan must not immediately reopen."""
    service = _service(tmp_path)
    # Open with score 15
    service.process_scan([_signal()], now=ENTRY_TIME)
    # Next scan: same ticker with market data that triggers a stop, AND a new
    # radar signal arrives for it in the same scan. The closed_tickers guard
    # must prevent reopening within the same process_scan call.
    signal_after_close = _signal(score=15)
    service.process_scan(
        [signal_after_close],
        _market_close(94.0),
        now=ENTRY_TIME + timedelta(hours=1),
    )

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    # Position was closed (stop hit) and not reopened within the same scan
    assert rows == {}, "closed_tickers guard must prevent same-scan reopen"


def test_holding_expiry_writes_exit_and_pnl_csv(tmp_path):
    service = _service(tmp_path)
    service.process_scan([_signal()], now=ENTRY_TIME)

    closed = service.process_scan(
        [],
        _market_close(105.0),
        now=ENTRY_TIME + timedelta(days=5),
    )

    assert len(closed) == 1
    assert closed[0]["hit"] == "timeout"
    assert closed[0]["pnl_pct"] == pytest.approx(5.0)
    # Risk budget 2,000 TL / 5 TL stop distance = 400 hypothetical shares.
    assert closed[0]["pnl_tl"] == pytest.approx(2_000.0)
    with service.csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["ticker"] == ROBUST
    assert rows[0]["reasons"] == "momentum | volume"


@pytest.mark.parametrize(
    ("close", "expected_hit"),
    [(94.0, "stop"), (111.0, "target")],
)
def test_stop_and_target_close_shadow_position(tmp_path, close, expected_hit):
    service = _service(tmp_path)
    service.process_scan([_signal()], now=ENTRY_TIME)

    closed = service.process_scan([], _market_close(close), now=ENTRY_TIME + timedelta(hours=1))

    assert closed[0]["hit"] == expected_hit


def test_duplicate_radar_does_not_create_second_open_position(tmp_path):
    service = _service(tmp_path)
    service.process_scan([_signal()], now=ENTRY_TIME)
    service.process_scan([_signal(price=101.0)], now=ENTRY_TIME + timedelta(hours=1))

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[ROBUST]["entry_price"] == 100.0


def test_shadow_disabled_writes_nothing(tmp_path):
    service = _service(tmp_path, SHADOW_ENABLED=False)

    service.process_scan([_signal()])

    assert list(tmp_path.iterdir()) == []


def test_daily_summary_sent_once_and_only_after_close(tmp_path):
    service = _service(tmp_path)
    notifier = MagicMock()
    notifier.send_message.return_value = True
    service.process_scan([_signal()], now=ENTRY_TIME)
    closed = service.process_scan([], _market_close(105.0), now=ENTRY_TIME + timedelta(days=5))

    assert service.maybe_send_daily_summary(
        notifier, now=ENTRY_TIME + timedelta(days=5), closed_this_scan=closed
    )
    assert not service.maybe_send_daily_summary(
        notifier, now=ENTRY_TIME + timedelta(days=5, hours=1), closed_this_scan=closed
    )
    notifier.send_message.assert_called_once()
    assert "açık 0, kapanan 1" in notifier.send_message.call_args.args[0]


def test_daily_summary_is_silent_without_closures(tmp_path):
    service = _service(tmp_path)
    notifier = MagicMock()

    assert not service.maybe_send_daily_summary(notifier, closed_this_scan=[])
    notifier.send_message.assert_not_called()


def test_cooldown_tickers_returns_set_without_csv(tmp_path):
    """When no CSV exists, _cooldown_tickers returns an empty set (no crash)."""
    service = _service(tmp_path)

    result = service._cooldown_tickers(ENTRY_TIME)

    assert result == set()


def test_cooldown_tickers_filters_only_recent_stops(tmp_path):
    """Only stop hits within COOLDOWN_DAYS are returned; old stops ignored."""
    service = _service(tmp_path, SHADOW_COOLDOWN_DAYS=3)
    # Write two stop rows: one recent, one old
    recent_stop_time = ENTRY_TIME + timedelta(hours=1)
    old_stop_time = ENTRY_TIME - timedelta(days=10)
    rows = [
        {
            "ticker": ROBUST,
            "entry_time": ENTRY_TIME.isoformat(),
            "entry_price": 100.0,
            "exit_time": recent_stop_time.isoformat(),
            "exit_price": 94.0,
            "score": 15.0,
            "agreement_ratio": 0.5,
            "pnl_pct": -6.0,
            "pnl_tl": -1200.0,
            "hit": "stop",
            "reasons": "test",
        },
        {
            "ticker": "OTHER.IS",
            "entry_time": (old_stop_time - timedelta(days=1)).isoformat(),
            "entry_price": 100.0,
            "exit_time": old_stop_time.isoformat(),
            "exit_price": 94.0,
            "score": 15.0,
            "agreement_ratio": 0.5,
            "pnl_pct": -6.0,
            "pnl_tl": -1200.0,
            "hit": "stop",
            "reasons": "test",
        },
    ]
    service.csv_path.parent.mkdir(parents=True, exist_ok=True)
    with service.csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    # Using `now` = recent_stop_time + 1 hour: the recent stop is in cooldown
    cooldown_set = service._cooldown_tickers(recent_stop_time + timedelta(hours=1))

    assert ROBUST in cooldown_set
    assert "OTHER.IS" not in cooldown_set


def test_opposite_signal_closes_shadow_position(tmp_path):
    """A shadow position must be closed when an opposite sell signal is received."""
    service = _service(tmp_path)
    service.process_scan([_signal(ticker=ROBUST, score=15)], now=ENTRY_TIME)

    # Send a sell signal
    sell_signal = _signal(ticker=ROBUST, score=-10, signal_type=SignalType.SELL)
    closed = service.process_scan(
        [sell_signal],
        _market_close(99.0),
        now=ENTRY_TIME + timedelta(hours=1),
    )

    assert len(closed) == 1
    assert closed[0]["hit"] == "opposite_signal"
    assert closed[0]["pnl_pct"] == pytest.approx(-1.0)

    rows = json.loads(service.open_path.read_text(encoding="utf-8"))
    assert rows == {}, "position must be closed and removed from open positions"
