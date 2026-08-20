"""Tests for daily report generation and day-scoped repository queries."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bist_bot.db.database import DatabaseManager
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.reports.daily_report import generate_daily_report
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import Signal, SignalType

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


@pytest.fixture
def memory_db(tmp_path):
    db_file = tmp_path / "test_report.db"
    return DatabaseManager(sqlite_path=str(db_file))


@pytest.fixture
def repo(memory_db):
    return SignalsRepository(memory_db)


def test_get_signals_and_scan_logs_for_day_boundary(repo, memory_db):
    target_day = date(2026, 8, 20)
    # Day start in Istanbul: 2026-08-20 00:00:00+03:00 -> 2026-08-19 21:00:00 UTC
    # Day end in Istanbul:   2026-08-21 00:00:00+03:00 -> 2026-08-20 21:00:00 UTC

    # In range (start edge + 1 min): 2026-08-20 00:01 TR = 2026-08-19 21:01 UTC
    t_in_start = datetime(2026, 8, 19, 21, 1, tzinfo=UTC)
    # In range (noon TR): 2026-08-20 12:00 TR = 2026-08-20 09:00 UTC
    t_in_mid = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    # In range (end edge - 1 min): 2026-08-20 23:59 TR = 2026-08-20 20:59 UTC
    t_in_end = datetime(2026, 8, 20, 20, 59, tzinfo=UTC)
    # Out of range (previous day late): 2026-08-19 23:59 TR = 2026-08-19 20:59 UTC
    t_out_prev = datetime(2026, 8, 19, 20, 59, tzinfo=UTC)
    # Out of range (next day early): 2026-08-21 00:01 TR = 2026-08-20 21:01 UTC
    t_out_next = datetime(2026, 8, 20, 21, 1, tzinfo=UTC)

    # Save signals
    for _idx, (ts, ticker, score) in enumerate(
        [
            (t_in_start, "THYAO.IS", 30.0),
            (t_in_mid, "GARAN.IS", 15.0),
            (t_in_end, "ASELS.IS", -10.0),
            (t_out_prev, "PREV.IS", 25.0),
            (t_out_next, "NEXT.IS", 25.0),
        ]
    ):
        sig = Signal(
            ticker=ticker,
            signal_type=SignalType.BUY
            if score > 20
            else (SignalType.WEAK_BUY if score > 0 else SignalType.WEAK_SELL),
            score=score,
            price=100.0,
            timestamp=ts,
        )
        repo.save_signal(sig)

    signals_day = repo.get_signals_for_day(target_day, tz=ISTANBUL_TZ)
    tickers_in_day = {s["ticker"] for s in signals_day}
    assert tickers_in_day == {"THYAO.IS", "GARAN.IS", "ASELS.IS"}
    assert "PREV.IS" not in tickers_in_day
    assert "NEXT.IS" not in tickers_in_day


def test_generate_daily_report_structure(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target_day = date(2026, 8, 20)

    # Seed signals across categories
    base_ts = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)  # 13:00 TR
    signals = [
        # AL (score >= 25)
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=35.0,
            price=300.0,
            timestamp=base_ts,
        ),
        # RADAR Tier A (20 - 24.9)
        Signal(
            ticker="TUPRS.IS",
            signal_type=SignalType.WEAK_BUY,
            score=22.0,
            price=150.0,
            timestamp=base_ts,
        ),
        # RADAR Tier B (15 - 19.9)
        Signal(
            ticker="PETKM.IS",
            signal_type=SignalType.WEAK_BUY,
            score=17.0,
            price=20.0,
            timestamp=base_ts,
        ),
        # RADAR Tier C (8 - 14.9)
        Signal(
            ticker="SISE.IS",
            signal_type=SignalType.WEAK_BUY,
            score=10.0,
            price=45.0,
            timestamp=base_ts,
        ),
        # SAT (score < 0)
        Signal(
            ticker="GARAN.IS",
            signal_type=SignalType.WEAK_SELL,
            score=-15.0,
            price=110.0,
            timestamp=base_ts,
        ),
        # Transition: THYAO later in session becomes RADAR
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.WEAK_BUY,
            score=18.0,
            price=298.0,
            timestamp=base_ts + timedelta(hours=2),
        ),
    ]

    for s in signals:
        repo.save_signal(s)

    # Seed scan log
    repo.save_scan_log(total=100, generated=6, buys=1, sells=0, actionable=1)

    params = StrategyParams.conservative()  # buy_threshold=25.0
    report_md = generate_daily_report(day=target_day, repo=repo, params=params, save_to_disk=True)

    assert "# BIST Bot Günlük Sinyal ve Tarama Raporu — 2026-08-20" in report_md
    assert "## 1. Genel Dağılım ve Özet" in report_md
    assert "## 2. Seans İçi Dağılım" in report_md
    assert "## 3. Aksiyon Alınabilir AL Sinyalleri" in report_md
    assert "THYAO" in report_md
    assert "## 4. RADAR Kademeleri" in report_md
    assert "TUPRS" in report_md
    assert "## 5. Satış / Negatif Baskılı Hisseler" in report_md
    assert "GARAN" in report_md
    assert "## 6. Gün İçi Durum Değişiklikleri" in report_md
    assert "THYAO" in report_md

    # Check file written on disk
    report_file = tmp_path / "results" / "daily_report_2026-08-20.md"
    assert report_file.exists()
    assert report_file.read_text(encoding="utf-8") == report_md
