"""A1 — backfill_paper_pnl tests (fixture DB, no fixed row-count thresholds)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from scripts.backfill_paper_pnl import (
    AUDIT_TABLE,
    STATUS_QUARANTINE_DIRECTION,
    STATUS_QUARANTINE_OUTLIER,
    STATUS_QUARANTINE_PRICE,
    STATUS_REPAIRED,
    resolve_direction_safe,
    run_backfill,
)

from bist_bot.db.database import Base, PaperTradeRecord


def _trade(
    *,
    ticker="TEST.IS",
    signal_type="🟢 AL",
    signal_price=100.0,
    exit_price=None,
    direction=None,
    profit=None,
):
    return PaperTradeRecord(
        ticker=ticker,
        signal_type=signal_type,
        signal_price=signal_price,
        signal_time=datetime.now(UTC),
        direction=direction,
        outcome="CLOSED",
        actual_profit_pct=profit,
        exit_price=exit_price,
        exit_date=datetime.now(UTC) if exit_price is not None else None,
        close_reason="STOP_HIT" if exit_price is not None else None,
    )


@pytest.fixture()
def engine():
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    AUDIT_TABLE.create(eng, checkfirst=True)
    yield eng
    eng.dispose()


def _insert(engine, *rows):
    with engine.begin() as conn:
        for row in rows:
            conn.execute(
                sa.insert(PaperTradeRecord).values(
                    ticker=row.ticker,
                    signal_type=row.signal_type,
                    signal_price=row.signal_price,
                    signal_time=row.signal_time,
                    direction=row.direction,
                    outcome=row.outcome,
                    actual_profit_pct=row.actual_profit_pct,
                    exit_price=row.exit_price,
                    exit_date=row.exit_date,
                    close_reason=row.close_reason,
                )
            )


def test_resolve_direction_prefers_persisted_then_signal_type():
    assert resolve_direction_safe("🟢 AL", None) == "long"
    assert resolve_direction_safe("🔴 SAT", None) == "short"
    assert resolve_direction_safe("🟢 AL", "short") == "short"  # persisted wins
    assert resolve_direction_safe("BOZUK_TIP", None) is None
    assert resolve_direction_safe("BOZUK_TIP", "long") == "long"


def test_long_profit_repair_includes_fees(engine):
    _insert(engine, _trade(signal_price=100.0, exit_price=110.0))  # +10% gross
    report = run_backfill(engine, apply=True)
    assert report["by_status"][STATUS_REPAIRED] == 1
    with engine.connect() as conn:
        stored = conn.execute(sa.select(PaperTradeRecord.actual_profit_pct)).scalar_one()
    # net = gross(10.0) - fee(~0.183): net < gross ve gross'a yakin
    assert stored == pytest.approx(10.0, abs=0.5)
    assert stored < 10.0


def test_long_loss_and_short_cases(engine):
    _insert(
        engine,
        _trade(ticker="L.IS", signal_price=100.0, exit_price=95.0),  # long zarar
        _trade(
            ticker="S1.IS", signal_type="🔴 SAT", signal_price=100.0, exit_price=90.0
        ),  # short kar
        _trade(
            ticker="S2.IS", signal_type="🔴 SAT", signal_price=100.0, exit_price=105.0
        ),  # short zarar
        _trade(ticker="Z.IS", signal_price=100.0, exit_price=100.0),  # sifir hareket
    )
    report = run_backfill(engine, apply=True)
    assert report["by_status"][STATUS_REPAIRED] == 4
    assert report["remaining_null_after"] == 0
    with engine.connect() as conn:
        profits = dict(
            conn.execute(
                sa.select(PaperTradeRecord.ticker, PaperTradeRecord.actual_profit_pct)
            ).all()
        )
    assert profits["L.IS"] == pytest.approx(-5.0, abs=0.5)
    assert profits["S1.IS"] == pytest.approx(10.0, abs=0.5)
    assert profits["S2.IS"] == pytest.approx(-5.0, abs=0.5)
    assert profits["Z.IS"] == pytest.approx(-0.183, abs=0.1)  # sadece komisyon


def test_quarantine_on_ambiguous_direction(engine):
    _insert(
        engine, _trade(ticker="Q.IS", signal_type="BOZUK", signal_price=100.0, exit_price=105.0)
    )
    report = run_backfill(engine, apply=True)
    assert report["by_status"].get(STATUS_QUARANTINE_DIRECTION) == 1
    assert report["by_status"].get(STATUS_REPAIRED) is None
    assert report["remaining_null_after"] == 1  # dokunulmadi


def test_quarantine_on_invalid_price(engine):
    _insert(
        engine,
        _trade(ticker="P1.IS", signal_price=0.0, exit_price=100.0),
        _trade(ticker="P2.IS", signal_price=100.0, exit_price=-5.0),
    )
    report = run_backfill(engine, apply=True)
    assert report["by_status"][STATUS_QUARANTINE_PRICE] == 2


def test_quarantine_on_outlier(engine):
    _insert(engine, _trade(ticker="O.IS", signal_price=100.0, exit_price=1000.0))  # +900%
    report = run_backfill(engine, apply=True)
    assert report["by_status"][STATUS_QUARANTINE_OUTLIER] == 1


def test_dry_run_writes_nothing(engine):
    _insert(engine, _trade(signal_price=100.0, exit_price=110.0))
    report = run_backfill(engine, apply=False)
    assert report["by_status"][STATUS_REPAIRED] == 1
    with engine.connect() as conn:
        profit = conn.execute(sa.select(PaperTradeRecord.actual_profit_pct)).scalar_one()
        audit_count = conn.execute(sa.select(sa.func.count()).select_from(AUDIT_TABLE)).scalar_one()
    assert profit is None
    assert audit_count == 0


def test_idempotent_second_run_finds_nothing(engine):
    _insert(engine, _trade(signal_price=100.0, exit_price=110.0))
    run_backfill(engine, apply=True)
    second = run_backfill(engine, apply=True)
    assert second["candidates"] == 0
    assert second["remaining_null_after"] == 0


def test_audit_rows_written(engine):
    _insert(
        engine,
        _trade(ticker="A.IS", signal_price=100.0, exit_price=110.0),
        _trade(ticker="B.IS", signal_type="BOZUK", signal_price=100.0, exit_price=110.0),
    )
    run_backfill(engine, apply=True)
    with engine.connect() as conn:
        statuses = dict(
            conn.execute(
                sa.select(AUDIT_TABLE.c.repair_status, sa.func.count()).group_by(
                    AUDIT_TABLE.c.repair_status
                )
            ).all()
        )
    assert statuses[STATUS_REPAIRED] == 1
    assert statuses[STATUS_QUARANTINE_DIRECTION] == 1


def test_crosscheck_blocks_apply_on_unexpected_drift(engine):
    # Dort gecerli satir + bes sasirtici satir → unexpected orani %55 → abort.
    rows = [
        _trade(ticker=f"OK{i}.IS", signal_price=100.0, exit_price=110.0, profit=9.817)
        for i in range(4)
    ] + [
        _trade(ticker=f"BAD{i}.IS", signal_price=100.0, exit_price=110.0, profit=50.0 + i)
        for i in range(5)
    ]
    _insert(engine, *rows)
    _insert(engine, _trade(ticker="TARGET.IS", signal_price=100.0, exit_price=110.0))
    report = run_backfill(engine, apply=True)
    assert "aborted" in report
    with engine.connect() as conn:
        profit = conn.execute(
            sa.select(PaperTradeRecord.actual_profit_pct).where(
                PaperTradeRecord.ticker == "TARGET.IS"
            )
        ).scalar_one()
    assert profit is None  # abort sonrasi hicbir sey yazilmadi


def test_allow_crosscheck_drift_bypasses_gate_and_repairs_drift(engine):
    # Drift satiri: saklanan PnL kardes isleme ait (kendi fiyatlari ~+9.82 net).
    _insert(
        engine,
        _trade(ticker="OK.IS", signal_price=100.0, exit_price=110.0, profit=9.817),
        _trade(ticker="DRIFT.IS", signal_price=100.0, exit_price=110.0, profit=2.5),
        _trade(ticker="NULL.IS", signal_price=100.0, exit_price=105.0),
    )
    report = run_backfill(engine, apply=True, allow_crosscheck_drift=True, repair_drift=True)
    assert "aborted" not in report
    assert report["crosscheck_bypassed"]
    assert report["drift_repaired"] == 1
    with engine.connect() as conn:
        profits = dict(
            conn.execute(
                sa.select(PaperTradeRecord.ticker, PaperTradeRecord.actual_profit_pct)
            ).all()
        )
        drift_audits = conn.execute(sa.select(AUDIT_TABLE.c.repair_status)).scalars().all()
    assert profits["DRIFT.IS"] == pytest.approx(9.82, abs=0.2)  # kendi fiyatlarindan
    assert profits["OK.IS"] == pytest.approx(9.817, abs=0.01)  # zaten dogru, dokunulmadi
    assert profits["NULL.IS"] == pytest.approx(4.8, abs=0.3)  # NULL onarimi
    assert "DRIFT_REPAIRED" in drift_audits
    assert "REPAIRED" in drift_audits


def test_drift_repair_idempotent(engine):
    _insert(engine, _trade(ticker="D.IS", signal_price=100.0, exit_price=110.0, profit=2.5))
    run_backfill(engine, apply=True, allow_crosscheck_drift=True, repair_drift=True)
    second = run_backfill(engine, apply=True, allow_crosscheck_drift=True, repair_drift=True)
    assert second["drift_repaired"] == 0  # ikinci kosuda drift kalmadi
