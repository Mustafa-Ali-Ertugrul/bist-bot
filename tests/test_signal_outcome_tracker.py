"""Signal outcome tracker tests (Z1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.services.signal_outcome_tracker import SignalOutcomeTracker
from bist_bot.strategy.signal_models import Signal, SignalType

ENTRY_TIME = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def _al_signal(
    ticker: str = "THYAO.IS",
    *,
    price: float = 100.0,
    stop: float = 95.0,
    target: float = 110.0,
    score: float = 30.0,
    ts: datetime = ENTRY_TIME,
) -> Signal:
    sig = Signal(
        ticker=ticker,
        signal_type=SignalType.BUY,
        score=score,
        price=price,
        stop_loss=stop,
        target_price=target,
        timestamp=ts,
    )
    sig.buy_threshold = 25.0
    return sig


def _tracker(tmp_path: Path, **overrides):
    settings = MagicMock()
    settings.OUTCOME_TRACKING_ENABLED = overrides.get("OUTCOME_TRACKING_ENABLED", True)
    settings.INITIAL_CAPITAL = 100000.0
    settings.MAX_TOTAL_RISK_PCT = 2.0
    for k, v in overrides.items():
        setattr(settings, k, v)
    db = MagicMock()
    return SignalOutcomeTracker(settings=settings, results_dir=tmp_path, db=db), db


def _market_data(ticker: str, close: float, high: float | None = None, low: float | None = None):
    # 1-min bar varsayımı: high/low aynı bar içinde
    h = high if high is not None else close
    low_val = low if low is not None else close
    df = pd.DataFrame({"close": [close], "high": [h], "low": [low_val]})
    return {ticker: {"trigger": df}}


def test_stop_hit(tmp_path):
    tracker, db = _tracker(tmp_path)
    sig = _al_signal()
    tracker.process_scan([sig], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    closed = tracker.process_scan(
        [], _market_data("THYAO.IS", 94.0), now=ENTRY_TIME + timedelta(hours=1)
    )
    assert len(closed) == 1
    assert closed[0]["outcome"] == "STOP_HIT"
    assert closed[0]["exit_price"] == 94.0


def test_target_hit(tmp_path):
    tracker, db = _tracker(tmp_path)
    sig = _al_signal()
    tracker.process_scan([sig], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    closed = tracker.process_scan(
        [], _market_data("THYAO.IS", 111.0), now=ENTRY_TIME + timedelta(hours=1)
    )
    assert closed[0]["outcome"] == "TARGET_HIT"


def test_same_bar_stop_priority(tmp_path):
    """Aynı 1dk bar içinde hem stop hem hedef tetiklenirse stop kazanır."""
    tracker, db = _tracker(tmp_path)
    sig = _al_signal(price=100.0, stop=95.0, target=105.0)
    tracker.process_scan([sig], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    # Bar with low 94 (stop) and high 106 (target) — both hit, stop wins
    closed = tracker.process_scan(
        [],
        _market_data("THYAO.IS", 100.0, high=106.0, low=94.0),
        now=ENTRY_TIME + timedelta(minutes=5),
    )
    assert closed[0]["outcome"] == "STOP_HIT"


def test_eod_close(tmp_path):
    tracker, db = _tracker(tmp_path)
    sig = _al_signal()
    tracker.process_scan([sig], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    # 20 Aug 2026 TR 18:01 → after continuous close (18:00) → EOD (B1)
    eod = datetime(2026, 8, 20, 15, 1, tzinfo=UTC)  # 18:01 TR
    closed = tracker.process_scan([], _market_data("THYAO.IS", 101.0), now=eod)
    assert closed[0]["outcome"] == "EOD_CLOSE"


def test_mfe_mae_tracked(tmp_path):
    tracker, db = _tracker(tmp_path)
    sig = _al_signal()
    tracker.process_scan([sig], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    # Update with high 108, low 97 → MFE 8%, MAE -3%
    tracker.process_scan(
        [],
        _market_data("THYAO.IS", 102.0, high=108.0, low=97.0),
        now=ENTRY_TIME + timedelta(minutes=10),
    )
    # Check open position has updated MFE/MAE
    import json

    open_pos = json.loads(tracker.open_path.read_text(encoding="utf-8"))
    assert open_pos["THYAO.IS"]["mfe_pct"] == 8.0
    assert open_pos["THYAO.IS"]["mae_pct"] == -3.0
    closed = tracker.process_scan(
        [],
        _market_data("THYAO.IS", 111.0, high=111.0, low=101.0),
        now=ENTRY_TIME + timedelta(hours=1),
    )
    assert closed[0]["mfe_pct"] == 11.0  # max high 111 → 11%
    assert closed[0]["mae_pct"] == -3.0


def test_dedup_one_open_per_ticker(tmp_path):
    tracker, db = _tracker(tmp_path)
    sig1 = _al_signal()
    sig2 = _al_signal(price=101.0, score=35.0)
    tracker.process_scan([sig1], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    tracker.process_scan(
        [sig2], _market_data("THYAO.IS", 101.0), now=ENTRY_TIME + timedelta(minutes=5)
    )
    import json

    open_pos = json.loads(tracker.open_path.read_text(encoding="utf-8"))
    assert len(open_pos) == 1
    assert open_pos["THYAO.IS"]["entry_price"] == 100.0


def test_db_write(tmp_path):
    # Use real DB for this test
    db_file = tmp_path / "outcome.db"
    manager = DatabaseManager(sqlite_path=str(db_file))
    repo = SignalsRepository(manager)
    from unittest.mock import MagicMock as MM

    settings = MM()
    settings.OUTCOME_TRACKING_ENABLED = True
    settings.INITIAL_CAPITAL = 100000.0
    settings.MAX_TOTAL_RISK_PCT = 2.0
    tracker = SignalOutcomeTracker(settings=settings, results_dir=tmp_path, db=repo)
    sig = _al_signal()
    # Save signal first to get record_id
    repo.save_signal(sig)
    assert sig.record_id is not None
    tracker.process_scan([sig], _market_data("THYAO.IS", 100.0), now=ENTRY_TIME)
    tracker.process_scan([], _market_data("THYAO.IS", 94.0), now=ENTRY_TIME + timedelta(hours=1))
    # Check DB outcome is set
    row = repo.get_signals(limit=1)[0]
    assert row["outcome"] == "STOP_HIT"
    assert row["outcome_price"] == 94.0


def test_scanner_wiring(tmp_path):
    from bist_bot.scanner import ScanService

    # Verify scanner has outcome tracker wired and calls it without error
    fetcher = MagicMock()
    engine = MagicMock()
    db = MagicMock()

    # db.save_signals should set record_id for signals
    def _save_signals(signals):
        for s in signals:
            s.record_id = 1

    db.save_signals.side_effect = _save_signals
    db.save_scan_log.return_value = None
    fetcher.fetch_multi_timeframe_all.return_value = {
        "THYAO.IS": {
            "trigger": pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0]}),
            "trend": pd.DataFrame({"close": [100.0]}),
        }
    }
    fetcher.get_last_skipped_tickers.return_value = []
    sig = _al_signal()
    engine.scan_all.return_value = [sig]
    engine.get_actionable_signals.return_value = [sig]
    engine.get_last_rejection_breakdown.return_value = {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": "test",
    }
    settings = MagicMock()
    settings.WATCHLIST = ["THYAO.IS"]
    settings.WATCHLIST_SOURCE = "test"
    settings.AGENT_ENABLED = False
    settings.agent = MagicMock()
    settings.agent.AGENT_ENABLED = False
    settings.PAPER_MODE = False
    settings.TRADING_ENABLED = False
    settings.OUTCOME_TRACKING_ENABLED = True
    settings.MTF_ENABLED = True
    settings.MTF_TREND_PERIOD = "6mo"
    settings.MTF_TREND_INTERVAL = "1d"
    settings.MTF_TRIGGER_PERIOD = "1mo"
    settings.MTF_TRIGGER_INTERVAL = "15m"
    settings.INITIAL_CAPITAL = 100000.0
    settings.MAX_TOTAL_RISK_PCT = 2.0
    notifier = MagicMock()
    scanner = ScanService(fetcher, engine, notifier, db, settings=settings, broker=MagicMock())
    result = scanner.scan_once()
    assert sig in result
