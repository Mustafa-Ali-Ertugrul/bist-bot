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

    # HOLD column appears in the session table header and rows.
    assert "| Saat (TR) | Toplam | AL | RADAR | SAT | HOLD | AL Veren Hisseler |" in report_md

    # Per-ticker AL rollup renders AL names with max score and R-R.
    assert "## 3.1. AL Rollup (Hisse Bazlı)" in report_md
    assert "| **THYAO** | 1 | +35.0 |" in report_md


def test_daily_report_rollup_repeat_and_sort(repo, tmp_path, monkeypatch):
    """AL Tekrar >=2 → 🔁 and sort is tekrar↓ then maks skor↓."""
    monkeypatch.chdir(tmp_path)
    target_day = date(2026, 8, 21)
    ts1 = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    ts2 = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    # THYAO 2x AL (tekrar 2, max 30), GARAN 1x AL (tekrar 1, max 40) → THYAO first due to repeat despite lower max
    for sig in [
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=25.0,
            price=100.0,
            stop_loss=95.0,
            target_price=110.0,
            timestamp=ts1,
        ),
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=30.0,
            price=102.0,
            stop_loss=96.0,
            target_price=112.0,
            timestamp=ts2,
        ),
        Signal(
            ticker="GARAN.IS",
            signal_type=SignalType.BUY,
            score=40.0,
            price=50.0,
            stop_loss=48.0,
            target_price=55.0,
            timestamp=ts1,
        ),
    ]:
        repo.save_signal(sig)
    repo.save_scan_log(total=100, generated=3, buys=3, sells=0, actionable=3)
    md = generate_daily_report(
        day=target_day, repo=repo, params=StrategyParams(buy_threshold=25), save_to_disk=False
    )
    assert "THYAO \U0001f501" in md  # 🔁
    assert md.index("THYAO") < md.index("GARAN")
    # header has 8 cols including İlk/Son | Son Fiyat | Stop | Hedef | R/R
    assert "| Hisse | AL Tekrar | Maks Skor | \u0130lk/Son | Son Fiyat | Stop | Hedef | R/R |" in md


def test_daily_report_rollup_rr_value_and_na(repo, tmp_path, monkeypatch):
    """R/R is (hedef-giris)/(giris-stop); N/A when stop/hedef missing or stop>=giris."""
    monkeypatch.chdir(tmp_path)
    target_day = date(2026, 8, 22)
    ts = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    # Valid R/R: entry 100, stop 95, target 110 → (10)/(5)=2.00
    repo.save_signal(
        Signal(
            ticker="VALID.IS",
            signal_type=SignalType.BUY,
            score=30,
            price=100.0,
            stop_loss=95.0,
            target_price=110.0,
            timestamp=ts,
        )
    )
    # Invalid: stop 100 >= entry 100 → N/A
    repo.save_signal(
        Signal(
            ticker="BAD.IS",
            signal_type=SignalType.BUY,
            score=30,
            price=100.0,
            stop_loss=100.0,
            target_price=110.0,
            timestamp=ts,
        )
    )
    # Missing: stop 0 → N/A
    repo.save_signal(
        Signal(
            ticker="NOSTOP.IS",
            signal_type=SignalType.BUY,
            score=30,
            price=100.0,
            stop_loss=0,
            target_price=110.0,
            timestamp=ts,
        )
    )
    repo.save_scan_log(total=100, generated=3, buys=3, sells=0, actionable=3)
    md = generate_daily_report(
        day=target_day, repo=repo, params=StrategyParams(buy_threshold=25), save_to_disk=False
    )
    # VALID row should contain 2.00
    assert "VALID" in md and "2.00" in md
    # BAD and NOSTOP rows should contain N/A in R/R column
    assert md.count("N/A") >= 2


def test_daily_report_rollup_dynamic_radar_and_note(repo, tmp_path, monkeypatch):
    """RADAR range is dynamic and kategori notu exists."""
    monkeypatch.chdir(tmp_path)
    target_day = date(2026, 8, 23)
    ts = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
    repo.save_signal(
        Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=30,
            price=100.0,
            stop_loss=95.0,
            target_price=110.0,
            timestamp=ts,
        )
    )
    repo.save_scan_log(total=100, generated=1, buys=1, sells=0, actionable=1)
    params = StrategyParams(buy_threshold=30, weak_buy_threshold=10)
    md = generate_daily_report(day=target_day, repo=repo, params=params, save_to_disk=False)
    assert "+10.0 ile +29.9" in md
    assert "Kategori bazl" in md


def test_daily_report_gate_demoted_radar_split(repo, tmp_path, monkeypatch):
    """RADAR rows with score >= threshold are gate-demotion: labelled and split.

    Gate-demotion (score preserved, type demoted by confluence/macro gate) is a
    distinct population from organic RADAR (0 < score < threshold) and must not
    pollute Kademe A or the 'AL >= threshold' report contract.
    """
    monkeypatch.chdir(tmp_path)
    target_day = date(2026, 8, 24)
    ts = datetime(2026, 8, 24, 7, 45, tzinfo=UTC)  # 10:45 TR

    # AL first, then gate-demoted RADAR (score preserved, HTF-neutral reason)
    repo.save_signal(
        Signal(
            ticker="GSRAY.IS",
            signal_type=SignalType.BUY,
            score=34.0,
            price=100.0,
            reasons=["MTF confluence: günlük trend LONG, 15dk tetik destekliyor"],
            timestamp=ts,
        )
    )
    repo.save_signal(
        Signal(
            ticker="GSRAY.IS",
            signal_type=SignalType.RADAR,
            score=28.6,
            price=101.0,
            reasons=["MTF confluence zayıf: üst zaman dilimi nötr (RADAR adayı)"],
            timestamp=ts + timedelta(hours=2),  # 12:45 TR
        )
    )
    # Macro-bear demoted RADAR on another ticker
    repo.save_signal(
        Signal(
            ticker="TUPRS.IS",
            signal_type=SignalType.RADAR,
            score=31.0,
            price=150.0,
            reasons=["Makro rejim BEAR → alım sinyali RADAR'a düşürüldü"],
            timestamp=ts,
        )
    )
    # Organic RADAR (below threshold) must stay in tiers, not the demoted list
    repo.save_signal(
        Signal(
            ticker="PETKM.IS",
            signal_type=SignalType.WEAK_BUY,
            score=22.0,
            price=20.0,
            timestamp=ts,
        )
    )
    repo.save_scan_log(total=100, generated=4, buys=1, sells=0, actionable=1)

    params = StrategyParams.conservative()  # buy_threshold=25.0
    md = generate_daily_report(day=target_day, repo=repo, params=params, save_to_disk=False)

    # Section 1: separate Gate-Demoted cohort row
    assert "**RADAR (Gate-Demoted)** | 2 |" in md
    assert "+28.6 ile +31.0" in md

    # Section 4: demoted subsection lists both with gate tags, not organic PETKM
    assert "Gate-Demoted (skor ≥ 25.0 ama kapı RADAR'a düşürdü) — Toplam: 2" in md
    demoted_section = md.split("### Gate-Demoted")[1].split("### Kademe A")[0]
    assert "TUPRS** (+31.0) [Macro Bear]" in demoted_section
    assert "GSRAY** (+28.6) [HTF Neutral]" in demoted_section
    assert "PETKM" not in demoted_section

    # Organic RADAR stays in Kademe A
    tier_a_section = md.split("### Kademe A")[1].split("### Kademe B")[0]
    assert "PETKM" in tier_a_section
    assert "GSRAY" not in tier_a_section

    # Section 6: transition shows RADARe marker with the gate reason + footnote
    assert "AL (10:45, +34.0) -> RADARe [HTF Neutral] (12:45, +28.6)" in md
    assert "`RADARe` = gate-demotion" in md
