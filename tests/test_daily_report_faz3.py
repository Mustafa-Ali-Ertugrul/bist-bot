"""Faz 3 P3/P4 tests: daily report §7 open positions, decay warning, liquidity column.

P3 contract:
- generate_daily_report renders "## 7. Açık Pozisyonlar" from
  results/signal_outcome_open.json (or injected open_positions)
- decay warning fires when entry score < buy_threshold AND local time >= 15:30
- before 15:30 or with a healthy score -> no warning

P4 contract:
- §3.1 rollup gains a "Liq (20g ort.)" column parsed from the signal's
  'Likidite: TL{X} ort. islem degeri' reason; below MIN_LIQUIDITY_VALUE_TL -> ⚠️
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from bist_bot.reports.daily_report import (
    _decay_warning,
    _format_liquidity,
    _parse_liquidity_tl,
    generate_daily_report,
)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


def _open_position(
    *,
    ticker: str = "THYAO.IS",
    score: float = 30.0,
    entry_ts: str = "2026-08-20T07:00:00+00:00",  # 10:00 TR
) -> dict:
    return {
        "signal_id": 1,
        "ticker": ticker,
        "score": score,
        "entry_ts": entry_ts,
        "side": "long",
        "entry_price": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "quantity": 100.0,
        "mfe_pct": 4.2,
        "mae_pct": -1.1,
        "max_high": 104.2,
        "min_low": 98.9,
    }


def _report_with_positions(positions, *, now: datetime, prices=None) -> str:
    return generate_daily_report(
        day=date(2026, 8, 20),
        repo=_empty_repo(),
        save_to_disk=False,
        open_positions=positions,
        prices=prices,
        now=now,
    )


class _EmptyRepo:
    """Minimal repo stub: no signals, no scan logs."""

    def get_signals_for_day(self, *_args, **_kwargs):
        return []

    def get_scan_logs_for_day(self, *_args, **_kwargs):
        return []


def _empty_repo() -> _EmptyRepo:
    return _EmptyRepo()


# ---------------------------------------------------------------------------
# P3 — §7 Açık Pozisyonlar + decay uyarısı
# ---------------------------------------------------------------------------


def test_section7_renders_open_positions():
    now = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)  # 14:00 TR — before decay window
    report = _report_with_positions([_open_position()], now=now, prices={"THYAO.IS": 103.0})

    assert "## 7. Açık Pozisyonlar" in report
    assert "**THYAO**" in report
    assert "+4.2" in report  # MFE
    assert "-1.1" in report  # MAE
    assert "+3.00" in report  # U.PnL from price 103 vs entry 100


def test_decay_warning_after_1530_when_score_below_threshold():
    # buy_threshold default (conservative profile may vary); use explicit check below.
    now = datetime(2026, 8, 20, 12, 31, tzinfo=UTC)  # 15:31 TR
    warning = _decay_warning(score=18.0, buy_threshold=25.0, now_local=now.astimezone(ISTANBUL_TZ))
    assert "⚠️" in warning
    assert "T+1" in warning


def test_no_decay_warning_before_1530():
    now = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)  # 14:00 TR
    warning = _decay_warning(score=18.0, buy_threshold=25.0, now_local=now.astimezone(ISTANBUL_TZ))
    assert warning == ""


def test_no_decay_warning_when_score_healthy():
    now = datetime(2026, 8, 20, 12, 31, tzinfo=UTC)  # 15:31 TR
    warning = _decay_warning(score=30.0, buy_threshold=25.0, now_local=now.astimezone(ISTANBUL_TZ))
    assert warning == ""


def test_report_decay_flag_appears_in_section7():
    now = datetime(2026, 8, 20, 12, 45, tzinfo=UTC)  # 15:45 TR
    report = _report_with_positions(
        [_open_position(score=18.0)], now=now
    )  # conservative buy_threshold=25 > 18

    assert "⚠️ skor eşiğin altında" in report


def test_report_no_decay_flag_before_window_or_healthy_score():
    now_early = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)  # 14:00 TR
    report_early = _report_with_positions([_open_position(score=18.0)], now=now_early)
    assert "⚠️ skor eşiğin altında" not in report_early

    now_late = datetime(2026, 8, 20, 12, 45, tzinfo=UTC)  # 15:45 TR
    report_ok = _report_with_positions([_open_position(score=30.0)], now=now_late)
    assert "⚠️ skor eşiğin altında" not in report_ok


def test_section7_empty_state():
    now = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
    report = _report_with_positions([], now=now)
    assert "## 7. Açık Pozisyonlar" in report
    assert "Açık pozisyon yok" in report


def test_section7_loads_from_open_json(tmp_path, monkeypatch):
    from bist_bot.reports import daily_report as dr

    open_file = tmp_path / "signal_outcome_open.json"
    open_file.write_text(json.dumps([_open_position()]), encoding="utf-8")
    monkeypatch.setattr(dr, "_OPEN_POSITIONS_PATH", open_file)

    loaded = dr._load_open_positions()
    assert len(loaded) == 1
    assert loaded[0]["ticker"] == "THYAO.IS"

    # Missing file -> empty list (no crash)
    monkeypatch.setattr(dr, "_OPEN_POSITIONS_PATH", tmp_path / "missing.json")
    assert dr._load_open_positions() == []


# ---------------------------------------------------------------------------
# P4 — Likidite kolonu
# ---------------------------------------------------------------------------


def test_parse_liquidity_tl_from_reason():
    reasons = ["R/R: 1:2.0 | Stop: Yüzdelik", "Likidite: TL12,345,678 ort. islem degeri"]
    assert _parse_liquidity_tl(reasons) == pytest.approx(12345678.0)


def test_parse_liquidity_tl_missing():
    assert _parse_liquidity_tl(["no liquidity here"]) is None
    assert _parse_liquidity_tl(None) is None


def test_format_liquidity_threshold_flags():
    cell_ok = _format_liquidity(8_000_000.0, min_threshold=5_000_000.0)
    assert "₺8.0M" in cell_ok
    assert "⚠️" not in cell_ok

    cell_low = _format_liquidity(3_200_000.0, min_threshold=5_000_000.0)
    assert "₺3.2M" in cell_low
    assert "⚠️" in cell_low

    assert _format_liquidity(None, 5_000_000.0) == "-"


def test_rollup_includes_liquidity_column(tmp_path):
    """End-to-end: AL signal with a liquidity reason shows the Liq cell."""
    from bist_bot.db.database import DatabaseManager
    from bist_bot.db.repositories.signals_repository import SignalsRepository
    from bist_bot.strategy.signal_models import Signal, SignalType

    db = DatabaseManager(sqlite_path=str(tmp_path / "liq.db"))
    repo = SignalsRepository(db)
    sig = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        timestamp=datetime(2026, 8, 20, 7, 0, tzinfo=UTC),
    )
    sig.reasons.append("Likidite: TL3,200,000 ort. islem degeri")  # below 5M gate
    repo.save_signal(sig)

    report = generate_daily_report(day=date(2026, 8, 20), repo=repo, save_to_disk=False)

    assert "Liq (20g ort.)" in report
    assert "₺3.2M ⚠️" in report
