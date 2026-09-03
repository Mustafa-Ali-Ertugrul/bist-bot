"""Sprint 2 Increment 2 — backfill_trade_ledger tests (fixture DB + tmp shadow files)."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from scripts.backfill_trade_ledger import (
    REASON_INVALID_ROW,
    REASON_INVALID_TIMESTAMP,
    REASON_MISSING_EXIT_PRICE,
    REASON_MISSING_EXIT_TIME,
    REASON_UNRESOLVED_DIRECTION,
    SOURCE_BACKFILL,
    aware_utc,
    resolve_direction_safe,
    run_backfill,
)
from sqlalchemy.orm import Session

from bist_bot.db.database import Base, PaperTradeRecord, SignalRecord, TradeLedgerRecord
from bist_bot.db.repositories.ledger_repository import (
    KIND_PAPER,
    KIND_SHADOW,
    STATUS_CLOSED,
    STATUS_OPEN,
)
from bist_bot.services.paper_trade_service import PaperTradeService
from bist_bot.strategy.signal_models import SignalType

ENTRY_TIME = datetime(2026, 7, 28, 8, 3, 6)
EXIT_TIME = datetime(2026, 7, 29, 10, 0, 0)

CSV_FIELDS = (
    "ticker",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "score",
    "agreement_ratio",
    "pnl_pct",
    "pnl_tl",
    "hit",
    "reasons",
)


def _paper(**overrides) -> PaperTradeRecord:
    defaults = dict(
        ticker="THYAO",
        signal_type=SignalType.BUY.value,
        signal_price=100.0,
        signal_time=ENTRY_TIME,
        direction="long",
        outcome="OPEN",
        score=7,
        regime="BULL",
    )
    defaults.update(overrides)
    return PaperTradeRecord(**defaults)


def _closed_paper(**overrides) -> PaperTradeRecord:
    defaults = dict(
        outcome="CLOSED",
        exit_price=110.0,
        exit_date=EXIT_TIME,
        close_time=EXIT_TIME,
        close_reason="TARGET_HIT",
    )
    defaults.update(overrides)
    return _paper(**defaults)


def _signal(**overrides) -> SignalRecord:
    defaults = dict(
        ticker="THYAO",
        signal_type=SignalType.BUY.value,
        timestamp=ENTRY_TIME,
    )
    defaults.update(overrides)
    return SignalRecord(**defaults)


def _csv_row(**overrides) -> dict:
    row = {field: "" for field in CSV_FIELDS}
    row.update(
        ticker="THYAO",
        entry_time=ENTRY_TIME.isoformat(),
        entry_price="100.0",
        exit_time=EXIT_TIME.isoformat(),
        exit_price="105.0",
        score="6.5",
        agreement_ratio="0.8",
        pnl_pct="5.0",
        pnl_tl="500",
        hit="target",
        reasons="r1;r2",
    )
    row.update(overrides)
    return row


@pytest.fixture()
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _add(engine, *records):
    with Session(engine) as session:
        session.add_all(records)
        session.commit()


def _ledger_rows(engine) -> list[TradeLedgerRecord]:
    with Session(engine) as session:
        return list(session.query(TradeLedgerRecord).order_by(TradeLedgerRecord.id).all())


def _write_shadow_csv(shadow_dir: Path, rows: list[dict]) -> None:
    with (shadow_dir / "shadow_pnl.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_shadow_open(shadow_dir: Path, items: dict) -> None:
    (shadow_dir / "shadow_open.json").write_text(json.dumps(items), encoding="utf-8")


# ---- helpers ---------------------------------------------------------------


def test_resolve_direction_safe_prefers_persisted_then_signal_type():
    assert resolve_direction_safe(SignalType.BUY.value, None) == "long"
    assert resolve_direction_safe(SignalType.SELL.value, None) == "short"
    assert resolve_direction_safe(SignalType.BUY.value, "short") == "short"  # persisted wins
    assert resolve_direction_safe("BOZUK_TIP", None) is None
    assert resolve_direction_safe("BOZUK_TIP", "long") == "long"


def test_aware_utc_normalizes_naive_as_utc_and_parses_iso():
    naive = datetime(2026, 7, 28, 8, 3, 6)
    assert aware_utc(naive) == naive.replace(tzinfo=UTC)
    assert aware_utc("2026-07-28T08:03:06Z") == naive.replace(tzinfo=UTC)
    assert aware_utc("2026-07-28T08:03:06") == naive.replace(tzinfo=UTC)
    assert aware_utc("2026-07-28T11:03:06+03:00") == naive.replace(tzinfo=UTC)
    assert aware_utc("COP") is None
    assert aware_utc(None) is None
    assert aware_utc(12345) is None


# ---- PAPER -----------------------------------------------------------------


def test_paper_open_row_inserted_as_open(engine, tmp_path):
    _add(engine, _paper())
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    rows = _ledger_rows(engine)
    assert report["paper_inserted"] == 1
    assert report["total_inserted"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == KIND_PAPER
    assert row.status == STATUS_OPEN
    assert row.paper_trade_id is not None
    assert row.source == SOURCE_BACKFILL
    assert row.direction == "long"
    assert row.exit_price is None
    assert row.exit_time is None
    assert row.gross_pnl_pct is None
    assert row.net_pnl_pct is None


def test_paper_closed_row_computes_gross_and_net(engine, tmp_path):
    _add(engine, _closed_paper(signal_price=100.0, exit_price=110.0, actual_profit_pct=None))
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["paper_inserted"] == 1
    assert row.status == STATUS_CLOSED
    assert row.gross_pnl_pct == pytest.approx(10.0)
    expected_net = PaperTradeService.net_profit_pct(100.0, 110.0, None, "long")
    assert row.net_pnl_pct == pytest.approx(expected_net)
    assert row.net_pnl_pct is not None and row.gross_pnl_pct is not None
    assert row.net_pnl_pct < row.gross_pnl_pct  # fees included
    assert row.close_reason == "TARGET_HIT"
    # paper_trades.actual_profit_pct must never be touched by this backfill.
    with Session(engine) as session:
        trade = session.query(PaperTradeRecord).first()
        assert trade is not None
        assert trade.actual_profit_pct is None


def test_paper_closed_exit_time_prefers_close_time_over_exit_date(engine, tmp_path):
    other = EXIT_TIME + timedelta(hours=2)
    _add(engine, _closed_paper(close_time=EXIT_TIME, exit_date=other))
    run_backfill(engine, shadow_dir=tmp_path, apply=True)
    row = _ledger_rows(engine)[0]
    assert aware_utc(row.exit_time) == EXIT_TIME.replace(tzinfo=UTC)


def test_paper_closed_exit_time_falls_back_to_exit_date(engine, tmp_path):
    _add(engine, _closed_paper(close_time=None, exit_date=EXIT_TIME))
    run_backfill(engine, shadow_dir=tmp_path, apply=True)
    row = _ledger_rows(engine)[0]
    assert aware_utc(row.exit_time) == EXIT_TIME.replace(tzinfo=UTC)


def test_paper_closed_short_direction_pnl(engine, tmp_path):
    _add(
        engine,
        _closed_paper(
            signal_type=SignalType.SELL.value,
            direction="short",
            signal_price=100.0,
            exit_price=90.0,
        ),
    )
    run_backfill(engine, shadow_dir=tmp_path, apply=True)
    row = _ledger_rows(engine)[0]
    assert row.direction == "short"
    assert row.gross_pnl_pct == pytest.approx(10.0)  # short win: price fell
    assert row.net_pnl_pct == pytest.approx(
        PaperTradeService.net_profit_pct(100.0, 90.0, None, "short")
    )


def test_paper_missing_exit_price_quarantined(engine, tmp_path):
    _add(engine, _closed_paper(exit_price=None))
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["paper_quarantined"] == 1
    assert report["paper_inserted"] == 0
    assert report["quarantine_reasons"][REASON_MISSING_EXIT_PRICE] == 1
    assert _ledger_rows(engine) == []


def test_paper_missing_exit_time_quarantined(engine, tmp_path):
    _add(engine, _closed_paper(close_time=None, exit_date=None))
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["paper_quarantined"] == 1
    assert report["quarantine_reasons"][REASON_MISSING_EXIT_TIME] == 1
    assert _ledger_rows(engine) == []


def test_paper_unresolved_direction_quarantined(engine, tmp_path):
    _add(engine, _paper(signal_type="BOZUK_TIP", direction=None))
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["paper_quarantined"] == 1
    assert report["quarantine_reasons"][REASON_UNRESOLVED_DIRECTION] == 1
    assert _ledger_rows(engine) == []


def test_paper_invalid_row_quarantined(engine, tmp_path):
    _add(engine, _paper(ticker="   "), _paper(signal_price=0.0))
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["paper_quarantined"] == 2
    assert report["quarantine_reasons"][REASON_INVALID_ROW] == 2
    assert _ledger_rows(engine) == []


def test_paper_validation_before_idempotency(engine, tmp_path):
    """A malformed row that already exists in the ledger is quarantined, not skipped."""
    trade = _paper(signal_type="BOZUK_TIP", direction=None)
    _add(engine, trade)
    with Session(engine) as session:
        first_trade = session.query(PaperTradeRecord).first()
        assert first_trade is not None
        trade_id = first_trade.id
        session.add(
            TradeLedgerRecord(
                kind=KIND_PAPER,
                ticker="THYAO",
                signal_type="BOZUK_TIP",
                direction="long",
                entry_price=100.0,
                entry_time=ENTRY_TIME,
                status=STATUS_OPEN,
                paper_trade_id=trade_id,
                source="live",
            )
        )
        session.commit()

    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)
    assert report["paper_quarantined"] == 1
    assert report["paper_skipped_existing"] == 0
    assert len(_ledger_rows(engine)) == 1  # only the pre-existing live row


# ---- signal join -------------------------------------------------------------


def test_signal_exact_match_links_signal_id(engine, tmp_path):
    _add(engine, _signal(), _paper())
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["signal_exact_matches"] == 1
    assert row.signal_id is not None


def test_signal_tolerance_match_within_five_minutes(engine, tmp_path):
    _add(engine, _signal(timestamp=ENTRY_TIME + timedelta(minutes=3)), _paper())
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["signal_tolerance_matches"] == 1
    assert row.signal_id is not None


def test_signal_beyond_tolerance_unmatched(engine, tmp_path):
    _add(engine, _signal(timestamp=ENTRY_TIME + timedelta(minutes=10)), _paper())
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["signal_unmatched"] == 1
    assert row.signal_id is None  # inserted anyway


def test_signal_ambiguous_inserts_null_not_quarantined(engine, tmp_path):
    _add(engine, _signal(), _signal(), _paper())  # two identical-timestamp signals
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    rows = _ledger_rows(engine)
    assert report["signal_ambiguous"] == 1
    assert report["paper_quarantined"] == 0
    assert report["paper_inserted"] == 1
    assert len(rows) == 1
    assert rows[0].signal_id is None


def test_signal_exact_requires_matching_type_for_paper(engine, tmp_path):
    """PAPER knows its signal_type: a same-timestamp signal of another type is not exact."""
    _add(engine, _signal(signal_type=SignalType.SELL.value), _paper())  # paper is AL
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["signal_exact_matches"] == 0
    assert report["signal_unmatched"] == 1
    assert row.signal_id is None


# ---- SHADOW closed (CSV) ------------------------------------------------------


def test_shadow_csv_closed_row_inserted(engine, tmp_path):
    _write_shadow_csv(tmp_path, [_csv_row()])
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    rows = _ledger_rows(engine)
    assert report["shadow_inserted"] == 1
    assert report["total_inserted"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == KIND_SHADOW
    assert row.status == STATUS_CLOSED
    assert row.direction == "long"
    assert row.gross_pnl_pct == pytest.approx(5.0)  # pnl_pct as-is
    assert row.net_pnl_pct is None
    assert row.close_reason == "target"
    assert row.source == SOURCE_BACKFILL
    assert row.agreement_ratio == pytest.approx(0.8)


def test_shadow_csv_unmatched_gets_radar_fallback(engine, tmp_path):
    _write_shadow_csv(tmp_path, [_csv_row()])  # no signals in DB
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["signal_unmatched"] == 1
    assert report["signal_type_fallbacks"] == 1
    assert row.signal_id is None
    assert row.signal_type == SignalType.RADAR.value


def test_shadow_csv_matched_takes_signal_type(engine, tmp_path):
    _add(engine, _signal(signal_type=SignalType.WEAK_BUY.value))
    _write_shadow_csv(tmp_path, [_csv_row()])
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    row = _ledger_rows(engine)[0]
    assert report["signal_exact_matches"] == 1
    assert report["signal_type_fallbacks"] == 0
    assert row.signal_type == SignalType.WEAK_BUY.value
    assert row.signal_id is not None


def test_shadow_csv_missing_exit_price_quarantined(engine, tmp_path):
    _write_shadow_csv(tmp_path, [_csv_row(exit_price="")])
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["shadow_quarantined"] == 1
    assert report["quarantine_reasons"][REASON_MISSING_EXIT_PRICE] == 1
    assert _ledger_rows(engine) == []


def test_shadow_csv_invalid_timestamps_quarantined(engine, tmp_path):
    _write_shadow_csv(
        tmp_path,
        [
            _csv_row(entry_time="COP"),
            _csv_row(exit_time="COP"),
            _csv_row(exit_time="", ticker="ASELS"),
        ],
    )
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["shadow_quarantined"] == 3
    assert report["quarantine_reasons"][REASON_INVALID_TIMESTAMP] == 2
    assert report["quarantine_reasons"][REASON_MISSING_EXIT_TIME] == 1
    assert _ledger_rows(engine) == []


def test_shadow_csv_invalid_row_quarantined(engine, tmp_path):
    _write_shadow_csv(
        tmp_path,
        [
            _csv_row(ticker="   "),
            _csv_row(entry_price="abc"),
            _csv_row(pnl_pct=""),
            _csv_row(exit_price="-5"),
        ],
    )
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["shadow_quarantined"] == 4
    assert report["quarantine_reasons"][REASON_INVALID_ROW] == 4
    assert _ledger_rows(engine) == []


def test_shadow_csv_duplicate_rows_both_preserved(engine, tmp_path):
    _write_shadow_csv(tmp_path, [_csv_row(), _csv_row()])
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["shadow_inserted"] == 2
    assert len(_ledger_rows(engine)) == 2


# ---- SHADOW open (JSON) ---------------------------------------------------------


def test_shadow_open_json_inserted_as_open(engine, tmp_path):
    _write_shadow_open(
        tmp_path,
        {
            "THYAO": {
                "ticker": "THYAO",
                "entry_price": 100.0,
                "entry_time": ENTRY_TIME.isoformat(),
                "stop": 95.0,
                "target": 110.0,
                "score": 6.0,
                "agreement_ratio": 0.7,
            }
        },
    )
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    rows = _ledger_rows(engine)
    assert report["shadow_open_inserted"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == KIND_SHADOW
    assert row.status == STATUS_OPEN
    assert row.stop_loss == pytest.approx(95.0)
    assert row.target_price == pytest.approx(110.0)
    assert row.exit_price is None
    assert row.signal_type == SignalType.RADAR.value  # unmatched fallback


def test_shadow_open_invalid_entry_quarantined(engine, tmp_path):
    _write_shadow_open(
        tmp_path,
        {
            "BAD1": {"ticker": "BAD1", "entry_price": None, "entry_time": ENTRY_TIME.isoformat()},
            "BAD2": {"ticker": "BAD2", "entry_price": 100.0, "entry_time": "COP"},
            "BAD3": "not-a-dict",
        },
    )
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["shadow_quarantined"] == 3
    assert report["shadow_open_inserted"] == 0
    assert _ledger_rows(engine) == []


def test_missing_shadow_files_graceful(engine, tmp_path):
    _add(engine, _paper())
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert report["shadow_seen"] == 0
    assert report["shadow_quarantined"] == 0
    assert report["paper_inserted"] == 1


# ---- modes / idempotency ---------------------------------------------------------


def test_dry_run_writes_nothing_but_counts_staged(engine, tmp_path):
    _add(engine, _paper(), _closed_paper(ticker="ASELS"))
    _write_shadow_csv(tmp_path, [_csv_row()])
    report = run_backfill(engine, shadow_dir=tmp_path, apply=False)

    assert report["dry_run"] is True
    assert report["paper_inserted"] == 2  # would-be inserts
    assert report["shadow_inserted"] == 1
    assert report["total_inserted"] == 0
    assert _ledger_rows(engine) == []


def test_idempotent_second_run_inserts_nothing(engine, tmp_path):
    _add(engine, _paper(), _closed_paper(ticker="ASELS"))
    _write_shadow_csv(tmp_path, [_csv_row()])
    _write_shadow_open(
        tmp_path,
        {"GARAN": {"ticker": "GARAN", "entry_price": 50.0, "entry_time": ENTRY_TIME.isoformat()}},
    )

    first = run_backfill(engine, shadow_dir=tmp_path, apply=True)
    assert first["total_inserted"] == 4
    second = run_backfill(engine, shadow_dir=tmp_path, apply=True)

    assert second["paper_inserted"] == 0
    assert second["paper_skipped_existing"] == 2
    assert second["shadow_inserted"] == 0
    assert second["shadow_skipped_existing"] == 2  # csv + open
    assert second["total_inserted"] == 0
    assert len(_ledger_rows(engine)) == 4


def test_existing_live_ledger_rows_block_reinsert(engine, tmp_path):
    trade = _paper()
    _add(engine, trade)
    with Session(engine) as session:
        live_first = session.query(PaperTradeRecord).first()
        assert live_first is not None
        trade_id = live_first.id
        session.add(
            TradeLedgerRecord(
                kind=KIND_PAPER,
                ticker="THYAO",
                signal_type=SignalType.BUY.value,
                direction="long",
                entry_price=100.0,
                entry_time=ENTRY_TIME,
                status=STATUS_OPEN,
                paper_trade_id=trade_id,
                source="live",
            )
        )
        session.add(
            TradeLedgerRecord(
                kind=KIND_SHADOW,
                ticker="THYAO",
                signal_type=SignalType.RADAR.value,
                direction="long",
                entry_price=100.0,
                entry_time=ENTRY_TIME,
                status=STATUS_CLOSED,
                exit_price=105.0,
                exit_time=EXIT_TIME,
                source="live",
            )
        )
        session.commit()
    _write_shadow_csv(tmp_path, [_csv_row()])

    report = run_backfill(engine, shadow_dir=tmp_path, apply=True)
    assert report["paper_skipped_existing"] == 1
    assert report["shadow_skipped_existing"] == 1
    assert report["total_inserted"] == 0
    assert len(_ledger_rows(engine)) == 2


def test_limit_applies_per_source(engine, tmp_path):
    _add(engine, _paper(), _paper(ticker="ASELS"))
    _write_shadow_csv(tmp_path, [_csv_row(), _csv_row(ticker="ASELS")])
    report = run_backfill(engine, shadow_dir=tmp_path, apply=True, limit=1)

    assert report["paper_seen"] == 1
    assert report["shadow_csv_seen"] == 1
    assert report["total_inserted"] == 2
