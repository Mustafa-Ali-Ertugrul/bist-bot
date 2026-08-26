"""A1 — Paper trade PnL backfill (veri onarımı).

Repairs paper_trades rows where the legacy close path wrote
``actual_profit_pct = NULL`` despite having ``exit_price`` recorded.

Rules (review-v2 hardened):
- Dry-run by default; ``--apply`` performs the write.
- Profit is computed with the production function
  ``PaperTradeService.net_profit_pct`` (fee-adjusted, direction aware).
- Direction resolution mirrors production: persisted column first, then
  signal type. Rows where neither resolves are QUARANTINED, never guessed.
- Cross-check pass recomputes PnL for already-filled rows and aborts
  ``--apply`` when unexpected drift is detected (legacy gross-fallback
  rows sit within the fee delta and are reported, not blocked).
- Every repaired/quarantined row is written to ``paper_pnl_backfill_audit``.
- Idempotent: only NULL rows are touched; re-running finds 0 candidates.

Usage:
    python scripts/backfill_paper_pnl.py                 # dry-run
    python scripts/backfill_paper_pnl.py --apply         # repair
    python scripts/backfill_paper_pnl.py --apply --add-constraint  # + CHECK guard
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

# Allow running both as a module and as a plain script from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bist_bot.db.database import Base, PaperTradeRecord
from bist_bot.services.paper_trade_service import (
    PaperTradeService,
    paper_direction_from_signal_type,
)
from bist_bot.strategy.signal_models import SignalType

VALID_DIRECTIONS = ("long", "short")

# Fee delta between legacy gross fallback and net calc is ~0.19 pct points;
# allow slack for price-scale rounding before flagging "unexpected" drift.
FEE_DELTA_TOLERANCE = 0.30
EXACT_TOLERANCE = 0.01
MAX_UNEXPECTED_CROSSCHECK_RATIO = 0.05
OUTLIER_ABS_PCT = 99.9

STATUS_REPAIRED = "REPAIRED"
STATUS_QUARANTINE_DIRECTION = "QUARANTINE_DIRECTION_AMBIGUOUS"
STATUS_QUARANTINE_PRICE = "QUARANTINE_PRICE_INVALID"
STATUS_QUARANTINE_OUTLIER = "QUARANTINE_OUTLIER"

AUDIT_TABLE = sa.Table(
    "paper_pnl_backfill_audit",
    Base.metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("paper_trade_id", sa.Integer, nullable=False, index=True),
    sa.Column("old_profit_pct", sa.Float, nullable=True),
    sa.Column("new_profit_pct", sa.Float, nullable=True),
    sa.Column("direction", sa.String(8), nullable=True),
    sa.Column("repair_status", sa.String(40), nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False, default=lambda: datetime.now(UTC)),
)


def resolve_direction_safe(signal_type: str, stored_direction: str | None) -> str | None:
    """Direction without guessing: persisted column, then signal type; None if unresolvable."""
    if stored_direction in VALID_DIRECTIONS:
        return stored_direction
    try:
        SignalType(signal_type)
    except ValueError:
        return None
    return paper_direction_from_signal_type(signal_type)


def _classify_crosscheck(diff: float) -> str:
    adiff = abs(diff)
    if adiff <= EXACT_TOLERANCE:
        return "exact"
    if adiff <= FEE_DELTA_TOLERANCE:
        return "fee_delta"
    return "unexpected"


def crosscheck_existing(engine: Engine) -> dict[str, int]:
    """Recompute PnL for rows that already carry a value; classify drift."""
    stats = {"checked": 0, "exact": 0, "fee_delta": 0, "unexpected": 0}
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                PaperTradeRecord.id,
                PaperTradeRecord.signal_type,
                PaperTradeRecord.direction,
                PaperTradeRecord.signal_price,
                PaperTradeRecord.exit_price,
                PaperTradeRecord.actual_profit_pct,
            ).where(
                PaperTradeRecord.actual_profit_pct.is_not(None),
                PaperTradeRecord.exit_price.is_not(None),
            )
        ).mappings()
        for row in rows:
            direction = resolve_direction_safe(row["signal_type"], row["direction"])
            if direction is None or row["signal_price"] <= 0:
                continue
            expected = PaperTradeService.net_profit_pct(
                row["signal_price"], row["exit_price"], None, direction
            )
            stats["checked"] += 1
            stats[_classify_crosscheck(row["actual_profit_pct"] - expected)] += 1
    return stats


def _audit_rows_for(engine: Engine) -> list[dict]:
    """Collect repair candidates with computed values; no writes here."""
    candidates: list[dict] = []
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                PaperTradeRecord.id,
                PaperTradeRecord.signal_type,
                PaperTradeRecord.direction,
                PaperTradeRecord.signal_price,
                PaperTradeRecord.exit_price,
            )
            .where(
                PaperTradeRecord.actual_profit_pct.is_(None),
                PaperTradeRecord.exit_price.is_not(None),
            )
            .order_by(PaperTradeRecord.id.asc())
        ).mappings()
        for row in rows:
            entry = dict(row)
            direction = resolve_direction_safe(entry["signal_type"], entry["direction"])
            if direction is None:
                candidates.append({**entry, "direction": None, "profit": None, "status": STATUS_QUARANTINE_DIRECTION})
                continue
            if entry["signal_price"] is None or entry["signal_price"] <= 0 or (entry["exit_price"] or 0) <= 0:
                candidates.append({**entry, "direction": direction, "profit": None, "status": STATUS_QUARANTINE_PRICE})
                continue
            profit = PaperTradeService.net_profit_pct(
                entry["signal_price"], entry["exit_price"], None, direction
            )
            if abs(profit) > OUTLIER_ABS_PCT:
                candidates.append({**entry, "direction": direction, "profit": None, "status": STATUS_QUARANTINE_OUTLIER})
                continue
            candidates.append({**entry, "direction": direction, "profit": profit, "status": STATUS_REPAIRED})
    return candidates


def _repair_drifted_rows(engine: Engine) -> int:
    """Recompute drifted PnL rows from own-row prices (audited old->new).

    Only touches rows whose stored PnL deviates from the own-row-price
    recomputation by more than the fee delta — i.e. values that provably
    belong to a sibling trade of the same ticker (pre-faz3 close bug).
    Idempotent: after repair the deviation is zero.
    """
    AUDIT_TABLE.create(engine, checkfirst=True)
    repaired = 0
    with engine.begin() as conn:
        rows = conn.execute(
            sa.select(
                PaperTradeRecord.id,
                PaperTradeRecord.signal_type,
                PaperTradeRecord.direction,
                PaperTradeRecord.signal_price,
                PaperTradeRecord.exit_price,
                PaperTradeRecord.actual_profit_pct,
            ).where(
                PaperTradeRecord.actual_profit_pct.is_not(None),
                PaperTradeRecord.exit_price.is_not(None),
            )
        ).mappings()
        for row in rows:
            direction = resolve_direction_safe(row["signal_type"], row["direction"])
            if direction is None or row["signal_price"] is None or row["signal_price"] <= 0:
                continue
            expected = PaperTradeService.net_profit_pct(
                row["signal_price"], row["exit_price"], None, direction
            )
            if abs(row["actual_profit_pct"] - expected) <= FEE_DELTA_TOLERANCE:
                continue
            if abs(expected) > OUTLIER_ABS_PCT:
                continue
            conn.execute(
                AUDIT_TABLE.insert().values(
                    paper_trade_id=row["id"],
                    old_profit_pct=row["actual_profit_pct"],
                    new_profit_pct=expected,
                    direction=direction,
                    repair_status="DRIFT_REPAIRED",
                )
            )
            conn.execute(
                sa.update(PaperTradeRecord)
                .where(PaperTradeRecord.id == row["id"])
                .values(actual_profit_pct=expected)
            )
            repaired += 1
    return repaired


def run_backfill(
    engine: Engine,
    *,
    apply: bool = False,
    limit: int | None = None,
    trade_id: int | None = None,
    allow_crosscheck_drift: bool = False,
    repair_drift: bool = False,
) -> dict:
    """Full pipeline: cross-check, classify, (optionally) write, verify.

    ``allow_crosscheck_drift``: the cross-check gate aborts when stored PnLs
    drift from own-row prices. Production drift was root-caused to the
    pre-faz3 wrong-trade-close bug (same ticker, two OPEN rows: profit
    computed from one trade's entry, written onto the sibling row), so the
    gate can be bypassed explicitly — never silently.
    ``repair_drift``: additionally recompute drifted rows from own-row
    prices (their stored value provably belongs to a different trade).
    """
    report: dict = {"apply": apply}

    report["crosscheck"] = crosscheck_existing(engine)
    cc = report["crosscheck"]
    checked = max(1, cc["checked"])
    drift_exceeded = cc["unexpected"] / checked > MAX_UNEXPECTED_CROSSCHECK_RATIO
    if drift_exceeded and not allow_crosscheck_drift:
        report["aborted"] = (
            f"cross-check beklenmedik sapma orani yuksek: {cc['unexpected']}/{cc['checked']}"
        )
        return report
    if drift_exceeded:
        report["crosscheck_bypassed"] = "izinli (bilinen yanlis-islem-kapatma hatasi)"

    candidates = _audit_rows_for(engine)
    if trade_id is not None:
        candidates = [c for c in candidates if c["id"] == trade_id]
    if limit is not None:
        candidates = candidates[:limit]

    by_status: dict[str, int] = {}
    for c in candidates:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    report["candidates"] = len(candidates)
    report["by_status"] = by_status

    if apply and candidates:
        AUDIT_TABLE.create(engine, checkfirst=True)
        with engine.begin() as conn:
            for c in candidates:
                conn.execute(
                    AUDIT_TABLE.insert().values(
                        paper_trade_id=c["id"],
                        old_profit_pct=None,
                        new_profit_pct=c["profit"],
                        direction=c["direction"],
                        repair_status=c["status"],
                    )
                )
                if c["status"] == STATUS_REPAIRED:
                    conn.execute(
                        sa.update(PaperTradeRecord)
                        .where(PaperTradeRecord.id == c["id"])
                        .values(actual_profit_pct=c["profit"])
                    )

    if apply and repair_drift:
        report["drift_repaired"] = _repair_drifted_rows(engine)
    else:
        report["drift_repaired"] = None

    with engine.connect() as conn:
        remaining = conn.execute(
            sa.select(sa.func.count())
            .select_from(PaperTradeRecord)
            .where(
                PaperTradeRecord.actual_profit_pct.is_(None),
                PaperTradeRecord.exit_price.is_not(None),
            )
        ).scalar_one()
    report["remaining_null_after"] = remaining
    return report


def add_check_constraint(engine: Engine) -> str:
    """Postgres-only guard: a closed trade must always carry its PnL."""
    if engine.dialect.name != "postgresql":
        return "SKIP: constraint sadece PostgreSQL icin"
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "ALTER TABLE paper_trades "
                "ADD CONSTRAINT chk_paper_profit_filled_on_exit "
                "CHECK (NOT (exit_price IS NOT NULL AND actual_profit_pct IS NULL))"
            )
        )
    return "OK: chk_paper_profit_filled_on_exit eklendi"


def _build_engine(db_url: str | None) -> Engine:
    if db_url:
        return sa.create_engine(db_url)
    from bist_bot.config.settings import settings

    url = getattr(settings, "DATABASE_URL", "") or "sqlite:///bist_signals.db"
    return sa.create_engine(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="dry-run yerine gercek yazim yap")
    parser.add_argument(
        "--allow-crosscheck-drift",
        action="store_true",
        help="cross-check drift gate'i atla (bilinen yanlis-islem-kapatma kaynakli drift icin)",
    )
    parser.add_argument(
        "--repair-drift",
        action="store_true",
        help="kendi satir fiyatlariyla uyusmayan PnL'leri de yeniden hesapla (audit'li)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--trade-id", type=int, default=None)
    parser.add_argument("--db", default=None, help="SQLAlchemy URL (default: DATABASE_URL)")
    parser.add_argument("--add-constraint", action="store_true", help="apply sonrasi CHECK constraint ekle (postgres)")
    args = parser.parse_args()

    engine = _build_engine(args.db)
    report = run_backfill(
        engine,
        apply=args.apply,
        limit=args.limit,
        trade_id=args.trade_id,
        allow_crosscheck_drift=args.allow_crosscheck_drift,
        repair_drift=args.repair_drift,
    )
    cc = report.get("crosscheck", {})
    print("== CROSS-CHECK ==")
    print(f"  kontrol: {cc.get('checked', 0)} | birebir: {cc.get('exact', 0)} | "
          f"fee-delta (bilinen): {cc.get('fee_delta', 0)} | beklenmedik: {cc.get('unexpected', 0)}")
    if "aborted" in report:
        print(f"ABORT: {report['aborted']}")
        return 2
    if "crosscheck_bypassed" in report:
        print(f"  GATE ATLANDI: {report['crosscheck_bypassed']}")
    print("== ONARIM ==")
    print(f"  aday: {report['candidates']}")
    for status, count in sorted(report.get("by_status", {}).items()):
        print(f"  {status}: {count}")
    print(f"  mod: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"  kalan NULL (exit dolu): {report['remaining_null_after']}")
    if report.get("drift_repaired") is not None:
        print(f"  drift onarimi (eski deger gecersiz): {report['drift_repaired']} satir")
    if args.apply and args.add_constraint:
        print("== CONSTRAINT ==")
        print(f"  {add_check_constraint(engine)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
