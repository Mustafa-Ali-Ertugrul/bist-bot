"""Startup reconciliation (missed sessions) testleri.

Bilgisayar kapaliyken EOD pass'i hic kosmaz; pozisyonlar yasar ve
stop/target uygulanmaz (TRALT 6.2 gun). Reconciliation, kacirilan seanslari
tarihsel gunluk barla oynatip bar bulunan ilk seansta kapatir.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from bist_bot.market_calendar import missed_session_days, session_eod_datetime
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.services.signal_outcome_tracker import SignalOutcomeTracker

TR = timezone(timedelta(hours=3))

# Cuma 2026-09-18 (BIST seansi) ve sonraki is gunleri.
FRI = datetime(2026, 9, 18)
MON = datetime(2026, 9, 21)
TUE = datetime(2026, 9, 22)
WED = datetime(2026, 9, 23)


def _daily(rows: list[tuple[str, float, float, float, float, float]]) -> pd.DataFrame:
    """(date, open, high, low, close, volume) -> normalized daily frame."""
    idx = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows], tz="UTC")
    return pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        },
        index=idx,
    )


def _bars(closes: dict[str, float], high: float | None = None, low: float | None = None):
    rows = []
    for d, c in closes.items():
        rows.append(
            (
                d,
                c,
                high if high is not None else c,
                low if low is not None else c,
                c,
                1000.0,
            )
        )
    return _daily(rows)


def _cfg(**over):
    base = dict(
        PAPER_MODE=True,
        TRAILING_STOP_ENABLED=False,
        TRAILING_STOP_PCT=2.0,
        PAPER_COOLDOWN_DAYS=0,
        OUTCOME_TRACKING_ENABLED=True,
        OUTCOME_MAX_HOLD_DAYS=5,
        MISSED_SESSION_RECONCILE=True,
        MISSED_SESSION_RECONCILE_MAX_DAYS=10,
    )
    base.update(over)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------
# market_calendar.missed_session_days
# --------------------------------------------------------------------------


def test_missed_session_days_counts_sessions_between_entry_and_today():
    entry = datetime(2026, 9, 18, 10, 0, tzinfo=TR)  # Cuma acilis
    now = datetime(2026, 9, 23, 9, 0, tzinfo=TR)  # Carsamba sabah, acilis oncesi
    days = missed_session_days(entry, now)
    assert days == [FRI.date(), MON.date(), TUE.date()]  # carsamba henuz EOD'gmedi


def test_missed_session_days_excludes_today_even_after_eod():
    entry = datetime(2026, 9, 18, 10, 0, tzinfo=TR)
    now = datetime(2026, 9, 22, 23, 0, tzinfo=TR)  # sali EOD gecti ama bugun sali
    days = missed_session_days(entry, now)
    # Bugun (sali) her zaman normal akisa ait: EOD pass / ilk tarama kapatir.
    assert TUE.date() not in days
    assert FRI.date() in days and MON.date() in days


def test_missed_session_days_skips_weekend_and_holiday():
    entry = datetime(2026, 9, 18, 10, 0, tzinfo=TR)
    now = datetime(2026, 9, 28, 9, 0, tzinfo=TR)
    days = missed_session_days(entry, now)
    for d in days:
        assert d.weekday() < 5


def test_missed_session_days_empty_when_entry_session_not_closed_yet():
    entry = datetime(2026, 9, 23, 10, 0, tzinfo=TR)
    now = datetime(2026, 9, 23, 11, 0, tzinfo=TR)
    assert missed_session_days(entry, now) == []


def test_missed_session_days_after_eod_entry_rolls_to_next_session():
    # Giris, ayni gunun EOD'undan sonra (post-close backfill) → o gun sayilmaz
    entry = datetime(2026, 9, 22, 20, 0, tzinfo=TR)
    now = datetime(2026, 9, 23, 9, 0, tzinfo=TR)
    assert TUE.date() not in missed_session_days(entry, now)


def test_missed_session_days_empty_when_position_is_fresh():
    entry = datetime(2026, 9, 23, 10, 0, tzinfo=TR)
    now = datetime(2026, 9, 23, 10, 30, tzinfo=TR)
    assert missed_session_days(entry, now) == []


# --------------------------------------------------------------------------
# SignalOutcomeTracker.reconcile_missed_sessions
# --------------------------------------------------------------------------


def _open_tracker(tmp_path: Path, entry_ts: str, **over):
    cfg = _cfg(**over)
    tracker = SignalOutcomeTracker(settings=cfg, results_dir=tmp_path, db=MagicMock())
    tracker._write_json(
        tracker.open_path,
        {
            "TRALT.IS": {
                "signal_id": 361,
                "ticker": "TRALT.IS",
                "score": 28.7,
                "entry_ts": entry_ts,
                "side": "long",
                "entry_price": 53.8,
                "stop": 52.8,
                "target": 54.9,
                "quantity": 185.87,
                "mfe_pct": 0.19,
                "mae_pct": 0.0,
                "max_high": 53.9,
                "min_low": 53.8,
            }
        },
    )
    return tracker


def test_reconcile_closes_stop_hit_at_missed_session_bar(tmp_path):
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00")
    fetcher = MagicMock()
    # Cuma bar'i stop'un altinda kapandi (gap-through), sonraki gunler dolgu yok
    fetcher.fetch_single.return_value = _bars(
        {"2026-09-18": 50.2, "2026-09-21": 51.0, "2026-09-22": 51.5}
    )
    summary = tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["stale"] == 1
    assert summary["closed"] == 1
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    assert len(rows) == 1
    assert rows[0]["outcome"] == "STOP_HIT"
    # cikis: stop barinda gap-through → min(close, stop) = 50.2
    assert float(rows[0]["exit_price"]) == 50.2
    # zaman damgasi Cuma EOD, bugun degil
    assert rows[0]["exit_ts"].startswith("2026-09-18")
    # acik pozisyon temizlendi
    assert tracker._load_json(tracker.open_path, {}) == {}


def test_reconcile_uses_first_session_with_a_bar(tmp_path):
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00")
    fetcher = MagicMock()
    # Cuma bar'i YOK; pazartesi bar'i var ve stop altinda
    fetcher.fetch_single.return_value = _bars({"2026-09-21": 50.0, "2026-09-22": 49.0})
    tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    assert rows[0]["exit_ts"].startswith("2026-09-21")
    assert float(rows[0]["exit_price"]) == 50.0


def test_reconcile_closes_at_first_missed_session_close(tmp_path):
    """Stop'a degeyse bile, bar bulunan ilk seans EOD_CLOSE ile kapanir."""
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00")
    fetcher = MagicMock()
    # Cuma kapanisi stop'un ustunde → EOD_CLOSE
    fetcher.fetch_single.return_value = _bars({"2026-09-18": 53.5, "2026-09-21": 53.0})
    tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    assert rows[0]["outcome"] == "EOD_CLOSE"
    assert rows[0]["exit_ts"].startswith("2026-09-18")


def test_reconcile_skips_when_no_bars_for_missed_sessions(tmp_path):
    """Bar yoksa pozisyon ACIK kalir — gunun normal akisi kapatir."""
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00")
    fetcher = MagicMock()
    # yalnizca bugunden once ama kacirilan gunlerin disinda bar
    fetcher.fetch_single.return_value = _bars({"2026-09-01": 53.0})
    summary = tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["closed"] == 0
    assert summary["skipped_no_bars"] == 1
    assert "TRALT.IS" in tracker._load_json(tracker.open_path, {})
    assert not tracker.csv_path.exists()


def test_reconcile_fetch_failure_leaves_position_open(tmp_path):
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00")
    fetcher = MagicMock()
    fetcher.fetch_single.side_effect = RuntimeError("network down")
    summary = tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["closed"] == 0
    assert "TRALT.IS" in tracker._load_json(tracker.open_path, {})


def test_reconcile_ignores_fresh_position(tmp_path):
    tracker = _open_tracker(tmp_path, "2026-09-23T07:44:02+00:00")
    fetcher = MagicMock()
    summary = tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["stale"] == 0
    fetcher.fetch_single.assert_not_called()
    assert "TRALT.IS" in tracker._load_json(tracker.open_path, {})


def test_reconcile_disabled_by_setting(tmp_path):
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00", MISSED_SESSION_RECONCILE=False)
    fetcher = MagicMock()
    summary = tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary == {"stale": 0, "closed": 0, "skipped_no_bars": 0, "errors": 0}
    fetcher.fetch_single.assert_not_called()


def test_reconcile_respects_max_days_window(tmp_path):
    tracker = _open_tracker(
        tmp_path, "2026-09-18T12:16:22+00:00", MISSED_SESSION_RECONCILE_MAX_DAYS=1
    )
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars(
        {"2026-09-18": 50.0, "2026-09-21": 50.0, "2026-09-22": 50.0}
    )
    tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    # sadece son gun (sali) → stop sali bar'inda
    assert rows[0]["exit_ts"].startswith("2026-09-22")


def test_reconcile_same_session_entry_ignores_daily_low(tmp_path):
    """Giriş seansının günlük low'u giriş-ÖNCESİ fiyatı içerir → sayılmaz.

    TKFEN regresyon korumasının replay karşılığı: aynı güne giren pozisyon
    close-only değerlendirilir.
    """
    tracker = _open_tracker(tmp_path, "2026-09-18T12:16:22+00:00")  # Cuma 15:16 TR
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars({"2026-09-18": 53.5}, high=53.9, low=50.0)
    tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    assert rows[0]["outcome"] == "EOD_CLOSE"
    assert float(rows[0]["exit_price"]) == 53.5


def test_reconcile_entry_session_low_ignored_next_session_low_honored(tmp_path):
    """Giriş seansının günlük low'u giriş-ÖNCESİ → sayılmaz; sonraki seansın
    low'u tamamen giriş-sonrası → stop sayılır."""
    tracker = _open_tracker(tmp_path, "2026-09-16T10:00:00+00:00")  # Çarşamba
    fetcher = MagicMock()
    # Çarşamba bar'ı: low stop altında ama giriş öncesi → EOD_CLOSE beklenir
    fetcher.fetch_single.return_value = _bars(
        {"2026-09-16": 53.5, "2026-09-17": 53.5}, high=54.0, low=50.0
    )
    tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    # İlk bar bulunan seans Çarşamba (giriş seansı) → low sayılmaz
    assert rows[0]["outcome"] == "EOD_CLOSE"
    assert rows[0]["exit_ts"].startswith("2026-09-16")


def test_reconcile_later_session_daily_low_fires_stop(tmp_path):
    """Giriş önceki seansta, bar bulunan seans giriş-sonrası → low stop tetikler."""
    tracker = _open_tracker(tmp_path, "2026-09-16T10:00:00+00:00")  # Çarşamba
    fetcher = MagicMock()
    # yalnızda Perşembe bar'ı var: low stop altında, close üstünde
    fetcher.fetch_single.return_value = _bars({"2026-09-17": 53.5}, high=54.0, low=50.0)
    tracker.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    rows = list(
        csv.DictReader(tracker.csv_path.open(encoding="utf-8", newline=""))
    )
    assert rows[0]["outcome"] == "STOP_HIT"
    assert float(rows[0]["exit_price"]) == 52.8
    assert rows[0]["exit_ts"].startswith("2026-09-17")


# --------------------------------------------------------------------------
# PaperTradeService.reconcile_missed_sessions
# --------------------------------------------------------------------------


def _open_paper(trade_id: int = 1, **over):
    t = SimpleNamespace(
        id=trade_id,
        ticker="TRALT.IS",
        signal_type="AL",
        signal_price=53.8,
        signal_time=datetime(2026, 9, 18, 12, 16, tzinfo=UTC),
        stop_loss=52.8,
        target_price=54.9,
        direction="long",
        score=28,
        regime="BULL",
    )
    for k, v in over.items():
        setattr(t, k, v)
    return t


def test_paper_reconcile_closes_at_missed_session_price(tmp_path):
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_open_paper()]
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars({"2026-09-18": 50.2, "2026-09-21": 51.0})
    svc = PaperTradeService(fetcher, db, settings=_cfg())
    summary = svc.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["closed"] == 1
    args, kwargs = db.close_paper_trade.call_args
    assert args[1] == 50.2  # exit_price
    assert args[2] == "STOP_HIT"
    # tarihsel zaman damgasi: Cuma EOD
    closed_at = kwargs["closed_at"]
    assert closed_at is not None
    assert closed_at.date() == FRI.date()
    assert closed_at.astimezone(TR) == session_eod_datetime(FRI.date())


def test_paper_reconcile_ignores_fresh_trade(tmp_path):
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _open_paper(signal_time=datetime(2026, 9, 23, 7, 44, tzinfo=UTC))
    ]
    fetcher = MagicMock()
    svc = PaperTradeService(fetcher, db, settings=_cfg())
    summary = svc.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["stale"] == 0
    db.close_paper_trade.assert_not_called()


def test_paper_reconcile_no_bars_leaves_open(tmp_path):
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_open_paper()]
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars({"2026-08-01": 53.0})
    svc = PaperTradeService(fetcher, db, settings=_cfg())
    summary = svc.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["closed"] == 0
    assert summary["skipped_no_bars"] == 1
    db.close_paper_trade.assert_not_called()


def test_paper_reconcile_paper_mode_off_is_noop():
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_open_paper()]
    fetcher = MagicMock()
    svc = PaperTradeService(fetcher, db, settings=_cfg(PAPER_MODE=False))
    summary = svc.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["closed"] == 0
    db.get_open_paper_trades.assert_not_called()


def test_paper_reconcile_target_hit(tmp_path):
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_open_paper()]
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars({"2026-09-18": 55.5})
    svc = PaperTradeService(fetcher, db, settings=_cfg())
    svc.reconcile_missed_sessions(fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC))
    args, _ = db.close_paper_trade.call_args
    assert args[2] == "TARGET_HIT"


def test_paper_reconcile_eod_close_when_between_levels(tmp_path):
    db = MagicMock()
    db.get_open_paper_trades.return_value = [_open_paper()]
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars({"2026-09-18": 53.5})
    svc = PaperTradeService(fetcher, db, settings=_cfg())
    svc.reconcile_missed_sessions(fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC))
    args, _ = db.close_paper_trade.call_args
    assert args[2] == "EOD_CLOSE"


def test_paper_reconcile_naive_signal_time_handled(tmp_path):
    db = MagicMock()
    db.get_open_paper_trades.return_value = [
        _open_paper(signal_time=datetime(2026, 9, 18, 12, 16))
    ]
    fetcher = MagicMock()
    fetcher.fetch_single.return_value = _bars({"2026-09-18": 50.2})
    svc = PaperTradeService(fetcher, db, settings=_cfg())
    summary = svc.reconcile_missed_sessions(
        fetcher, now=datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    )
    assert summary["closed"] == 1


# --------------------------------------------------------------------------
# Entegrasyon: gercek DB ile close_paper_trade(closed_at=...)
# --------------------------------------------------------------------------


def test_close_paper_trade_persists_historical_timestamp(tmp_path):
    from bist_bot.db.database import DatabaseManager
    from bist_bot.db.repositories.portfolio_repository import PortfolioRepository

    mgr = DatabaseManager(sqlite_path=str(tmp_path / "p.db"))
    repo = PortfolioRepository(mgr)
    trade_id = repo.add_paper_trade(
        ticker="TRALT.IS",
        signal_type="AL",
        signal_price=53.8,
        signal_time=datetime(2026, 9, 18, 12, 16, tzinfo=UTC),
        stop_loss=52.8,
        target_price=54.9,
        score=28,
        regime="BULL",
        direction="long",
    )
    assert trade_id
    hist = session_eod_datetime(FRI.date()).astimezone(UTC)
    repo.close_paper_trade(
        "TRALT.IS", 50.2, "STOP_HIT", actual_profit_pct=-6.7, trade_id=trade_id, closed_at=hist
    )
    closed = repo.get_closed_trades()
    assert len(closed) == 1
    # SQLite geri okumada naive döner; değer UTC karşılığıyla birebir aynı olmalı.
    assert closed[0].close_time.replace(tzinfo=UTC) == hist
    assert closed[0].close_reason == "STOP_HIT"
    assert closed[0].exit_price == 50.2
    assert repo.get_open_paper_trades() == []


def test_close_paper_trade_defaults_to_now(tmp_path):
    from bist_bot.db.database import DatabaseManager
    from bist_bot.db.repositories.portfolio_repository import PortfolioRepository

    mgr = DatabaseManager(sqlite_path=str(tmp_path / "p2.db"))
    repo = PortfolioRepository(mgr)
    trade_id = repo.add_paper_trade(
        ticker="X.IS",
        signal_type="AL",
        signal_price=100.0,
        signal_time=datetime.now(UTC),
        stop_loss=95.0,
        target_price=110.0,
        score=30,
        regime="BULL",
        direction="long",
    )
    repo.close_paper_trade("X.IS", 101.0, "TARGET_HIT", trade_id=trade_id)
    closed = repo.get_closed_trades()
    assert closed[0].close_time is not None
    close_time = closed[0].close_time.replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - close_time).total_seconds()) < 120


@pytest.mark.parametrize(
    "entry,now,expected",
    [
        # (Pzt 10:00 giris, Cars 09:00) → Pzt + Sali
        (
            datetime(2026, 9, 21, 10, 0, tzinfo=TR),
            datetime(2026, 9, 22, 9, 0, tzinfo=TR),
            [datetime(2026, 9, 21).date()],
        ),
    ],
)
def test_missed_session_days_parametrized(entry, now, expected):
    assert missed_session_days(entry, now) == expected
