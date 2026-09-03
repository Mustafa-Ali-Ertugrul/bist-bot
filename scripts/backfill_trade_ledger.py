"""Sprint 2 Increment 2 — trade_ledger historical backfill.

Fills the unified ``trade_ledger`` table from the two authoritative
historical sources that predate the Sprint 2 dual-write:

- ``paper_trades`` rows (OPEN and CLOSED) -> ``kind='PAPER'``
- shadow CSV (``shadow_pnl.csv``) closed rows -> ``kind='SHADOW'``
- shadow open state (``shadow_open.json``) -> ``kind='SHADOW'`` OPEN rows

Design rules (frozen):

- Dry-run by default; ``--apply`` performs a single transactional insert.
- Idempotent: paper rows keyed by ``paper_trade_id``; shadow closed rows by
  ``(ticker, entry_time, exit_time)``; shadow open rows by
  ``(ticker, entry_time)``. Re-running inserts nothing new.
- Malformed rows are quarantined (counted + listed), never guessed.
  Validation happens BEFORE the idempotency check: a malformed row that
  already exists in the ledger is still reported as quarantined.
- Direction: persisted ``paper_trades.direction`` wins; otherwise derived
  from ``signal_type`` via ``paper_direction_from_signal_type`` after strict
  ``SignalType`` validation (that helper silently returns 'long' for unknown
  types). Unresolvable -> quarantine ``unresolved_direction``. Shadow rows
  are always ``long`` (buy-side radar ledger).
- ``signal_id`` join: exact ``(ticker, timestamp[, signal_type])`` first,
  then a +/-5 minute tolerance window. Ambiguous (>1 candidate) -> insert
  with ``signal_id=NULL`` and count ``signal_ambiguous`` (NOT quarantined).
  Unmatched shadow rows get ``signal_type`` fallback ``RADAR`` (never a
  fabricated ``signal_id``).
- PAPER closed: exit price strictly from ``exit_price`` (never
  ``close_price``); exit time from ``close_time`` else ``exit_date``;
  gross recomputed direction-aware, net via
  ``PaperTradeService.net_profit_pct``. ``actual_profit_pct`` is never
  touched. PAPER open: status OPEN, exit/gross/net NULL.
- Timestamps: naive DB datetimes are UTC by project contract; ISO strings
  parse via ``fromisoformat``. Both sides normalized before comparison.

Usage:
    python scripts/backfill_trade_ledger.py                     # dry-run
    python scripts/backfill_trade_ledger.py --apply             # write
    python scripts/backfill_trade_ledger.py --db URL --shadow-dir results
    python scripts/backfill_trade_ledger.py --limit 500         # per source
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

# Allow running both as a module and as a plain script from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bist_bot.db.database import (
    PaperTradeRecord,
    SignalRecord,
    TradeLedgerRecord,
)
from bist_bot.db.repositories.ledger_repository import (
    KIND_PAPER,
    KIND_SHADOW,
    STATUS_CLOSED,
    STATUS_OPEN,
)
from bist_bot.services.paper_trade_service import (
    PaperTradeService,
    paper_direction_from_signal_type,
)
from bist_bot.strategy.signal_models import SignalType

VALID_DIRECTIONS = ("long", "short")
SIGNAL_TOLERANCE = timedelta(minutes=5)
SOURCE_BACKFILL = "backfill"
OUTCOME_CLOSED = "CLOSED"

REASON_MISSING_EXIT_PRICE = "missing_exit_price"
REASON_MISSING_EXIT_TIME = "missing_exit_time"
REASON_UNRESOLVED_DIRECTION = "unresolved_direction"
REASON_INVALID_TIMESTAMP = "invalid_timestamp"
REASON_INVALID_ROW = "invalid_source_row"

SIGNAL_STAT_KEYS = {
    "exact": "signal_exact_matches",
    "tolerance": "signal_tolerance_matches",
    "unmatched": "signal_unmatched",
    "ambiguous": "signal_ambiguous",
}

# Uniform key set for executemany inserts: SQLAlchemy derives the column list
# from the FIRST dict, so every staged row must carry every key explicitly.
LEDGER_FIELDS = (
    "kind",
    "ticker",
    "signal_type",
    "direction",
    "score",
    "regime",
    "entry_price",
    "entry_time",
    "stop_loss",
    "target_price",
    "agreement_ratio",
    "status",
    "exit_price",
    "exit_time",
    "close_reason",
    "gross_pnl_pct",
    "net_pnl_pct",
    "paper_trade_id",
    "signal_id",
    "source",
)


def resolve_direction_safe(signal_type: str, stored_direction: str | None) -> str | None:
    """Direction without guessing: persisted column, then signal type.

    ``paper_direction_from_signal_type`` returns 'long' for unknown types,
    so the signal type is validated against ``SignalType`` first. Returns
    None when neither source yields a direction (caller quarantines).
    """
    if stored_direction in VALID_DIRECTIONS:
        return stored_direction
    try:
        SignalType(signal_type)
    except ValueError:
        return None
    return paper_direction_from_signal_type(signal_type)


def aware_utc(value: Any) -> datetime | None:
    """Normalize a datetime-ish value into aware UTC; None if unparseable.

    Project contract: BIST DB timestamps are UTC. SQLite round-trips
    ``DateTime`` columns as naive datetimes, so naive values get UTC
    attached explicitly — never a local-timezone assumption. ISO strings
    (CSV/JSON) parse through ``datetime.fromisoformat``. Anything else
    yields None so callers quarantine instead of fabricating a time.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _load_signal_index(engine: Engine) -> dict[str, list[tuple[datetime, str, int]]]:
    """ticker -> list of (timestamp_utc, signal_type, signal_id)."""
    index: dict[str, list[tuple[datetime, str, int]]] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                SignalRecord.id,
                SignalRecord.ticker,
                SignalRecord.signal_type,
                SignalRecord.timestamp,
            )
        ).all()
    for signal_id, ticker, signal_type, ts in rows:
        when = aware_utc(ts)
        if when is None or not ticker:
            continue
        index.setdefault(ticker, []).append((when, signal_type, signal_id))
    return index


def _match_signal(
    index: dict[str, list[tuple[datetime, str, int]]],
    ticker: str,
    when: datetime,
    known_type: str | None,
) -> tuple[str, int | None, str | None]:
    """Resolve a ledger entry against the signals table.

    Returns ``(status, signal_id, matched_type)`` where status is one of
    ``exact`` / ``tolerance`` / ``ambiguous`` / ``unmatched``. ``known_type``
    filters candidates for PAPER rows (persisted type is known); shadow
    rows pass None. Ambiguous means >1 candidate at the same stage — the
    caller inserts with ``signal_id=NULL`` and counts it.
    """
    candidates = index.get(ticker, [])

    def type_ok(sig_type: str) -> bool:
        return known_type is None or sig_type == known_type

    exact = [c for c in candidates if c[0] == when and type_ok(c[1])]
    if len(exact) == 1:
        return "exact", exact[0][2], exact[0][1]
    if len(exact) > 1:
        return "ambiguous", None, None
    near = [
        c
        for c in candidates
        if c[0] != when and abs(c[0] - when) <= SIGNAL_TOLERANCE and type_ok(c[1])
    ]
    if len(near) == 1:
        return "tolerance", near[0][2], near[0][1]
    if len(near) > 1:
        return "ambiguous", None, None
    return "unmatched", None, None


def _existing_keys(engine: Engine) -> dict[str, set[Any]]:
    """Preload existing ledger identity keys for idempotency.

    All existing ledger rows count regardless of source/status: a row
    written live or by a previous backfill run is never re-inserted.
    """
    keys: dict[str, set[Any]] = {
        "paper_ids": set(),
        "shadow_open": set(),
        "shadow_closed": set(),
    }
    try:
        if not sa.inspect(engine).has_table("trade_ledger"):
            return keys
    except sa.exc.SQLAlchemyError:
        return keys
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                TradeLedgerRecord.kind,
                TradeLedgerRecord.ticker,
                TradeLedgerRecord.paper_trade_id,
                TradeLedgerRecord.entry_time,
                TradeLedgerRecord.exit_time,
            )
        ).all()
    for kind, ticker, paper_id, entry, exit_ in rows:
        if kind == KIND_PAPER:
            if paper_id is not None:
                keys["paper_ids"].add(paper_id)
            continue
        if kind != KIND_SHADOW or not ticker:
            continue
        entry_dt = aware_utc(entry)
        if entry_dt is None:
            continue
        exit_dt = aware_utc(exit_)
        if exit_dt is None:
            keys["shadow_open"].add((ticker, entry_dt.isoformat()))
        else:
            keys["shadow_closed"].add((ticker, entry_dt.isoformat(), exit_dt.isoformat()))
    return keys


def _paper_candidates(engine: Engine, limit: int | None) -> list[Any]:
    stmt = sa.select(
        PaperTradeRecord.id,
        PaperTradeRecord.ticker,
        PaperTradeRecord.signal_type,
        PaperTradeRecord.signal_price,
        PaperTradeRecord.signal_time,
        PaperTradeRecord.stop_loss,
        PaperTradeRecord.target_price,
        PaperTradeRecord.score,
        PaperTradeRecord.regime,
        PaperTradeRecord.direction,
        PaperTradeRecord.outcome,
        PaperTradeRecord.exit_price,
        PaperTradeRecord.exit_date,
        PaperTradeRecord.close_reason,
        PaperTradeRecord.close_time,
    ).order_by(PaperTradeRecord.id.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    with engine.connect() as conn:
        return list(conn.execute(stmt).mappings().all())


def _shadow_csv_rows(shadow_dir: Path, limit: int | None) -> list[dict[str, Any]]:
    csv_path = shadow_dir / "shadow_pnl.csv"
    if not csv_path.exists():
        return []
    try:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return []
    if limit is not None:
        rows = rows[:limit]
    return rows


def _shadow_open_items(shadow_dir: Path, limit: int | None) -> list[tuple[str, Any]]:
    open_path = shadow_dir / "shadow_open.json"
    if not open_path.exists():
        return []
    try:
        payload = json.loads(open_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    items = list(payload.items())
    if limit is not None:
        items = items[:limit]
    return items


def run_backfill(
    engine: Engine,
    *,
    shadow_dir: str | Path = "results",
    apply: bool = False,
    limit: int | None = None,
) -> dict:
    """Read both historical sources, stage ledger rows, optionally insert.

    ``limit`` caps candidates per source (paper rows / shadow CSV rows /
    shadow_open entries). Dry-run stages everything and reports would-be
    inserts but writes nothing (``total_inserted`` stays 0). Apply inserts
    all staged rows in a single transaction.
    """
    shadow_path = Path(shadow_dir)
    report: dict[str, Any] = {
        "apply": apply,
        "dry_run": not apply,
        "paper_seen": 0,
        "paper_inserted": 0,
        "paper_skipped_existing": 0,
        "paper_quarantined": 0,
        "shadow_seen": 0,
        "shadow_inserted": 0,
        "shadow_skipped_existing": 0,
        "shadow_quarantined": 0,
        "shadow_csv_seen": 0,
        "shadow_csv_inserted": 0,
        "shadow_open_seen": 0,
        "shadow_open_inserted": 0,
        "signal_exact_matches": 0,
        "signal_tolerance_matches": 0,
        "signal_unmatched": 0,
        "signal_ambiguous": 0,
        "signal_type_fallbacks": 0,
        "total_inserted": 0,
        "total_skipped": 0,
        "total_quarantined": 0,
        "quarantine_reasons": {},
        "quarantine_details": [],
    }
    reasons: dict[str, int] = report["quarantine_reasons"]
    staged: list[dict[str, Any]] = []

    def quarantine(source: str, identifier: str, reason: str) -> None:
        report[f"{source}_quarantined"] += 1
        reasons[reason] = reasons.get(reason, 0) + 1
        report["quarantine_details"].append(
            {"source": source, "source_identifier": identifier, "reason": reason}
        )

    signal_index = _load_signal_index(engine)
    keys = _existing_keys(engine)

    # ---- PAPER -----------------------------------------------------------
    for row in _paper_candidates(engine, limit):
        report["paper_seen"] += 1
        identifier = f"paper#{row['id']}"
        ticker = (row["ticker"] or "").strip()
        if not ticker:
            quarantine("paper", identifier, REASON_INVALID_ROW)
            continue
        direction = resolve_direction_safe(row["signal_type"], row["direction"])
        if direction is None:
            quarantine("paper", identifier, REASON_UNRESOLVED_DIRECTION)
            continue
        entry_price = _parse_float(row["signal_price"])
        if entry_price is None or entry_price <= 0:
            quarantine("paper", identifier, REASON_INVALID_ROW)
            continue
        entry_time = aware_utc(row["signal_time"])
        if entry_time is None:
            quarantine("paper", identifier, REASON_INVALID_TIMESTAMP)
            continue
        status, signal_id, _matched_type = _match_signal(
            signal_index, ticker, entry_time, row["signal_type"]
        )
        report[SIGNAL_STAT_KEYS[status]] += 1
        if row["id"] in keys["paper_ids"]:
            report["paper_skipped_existing"] += 1
            continue

        base = {
            "kind": KIND_PAPER,
            "ticker": ticker,
            "signal_type": row["signal_type"],
            "direction": direction,
            "score": _parse_float(row["score"]),
            "regime": row["regime"],
            "entry_price": entry_price,
            "entry_time": entry_time,
            "stop_loss": _parse_float(row["stop_loss"]),
            "target_price": _parse_float(row["target_price"]),
            "paper_trade_id": row["id"],
            "signal_id": signal_id,
            "source": SOURCE_BACKFILL,
        }
        if row["outcome"] == OUTCOME_CLOSED:
            exit_price = _parse_float(row["exit_price"])
            if exit_price is None:
                quarantine("paper", identifier, REASON_MISSING_EXIT_PRICE)
                continue
            if exit_price <= 0:
                quarantine("paper", identifier, REASON_INVALID_ROW)
                continue
            exit_time = aware_utc(row["close_time"]) or aware_utc(row["exit_date"])
            if exit_time is None:
                raw_present = not _is_blank(row["close_time"]) or not _is_blank(row["exit_date"])
                reason = REASON_INVALID_TIMESTAMP if raw_present else REASON_MISSING_EXIT_TIME
                quarantine("paper", identifier, reason)
                continue
            if direction == "short":
                gross = (entry_price - exit_price) / entry_price * 100.0
            else:
                gross = (exit_price - entry_price) / entry_price * 100.0
            staged.append(
                {
                    **base,
                    "status": STATUS_CLOSED,
                    "exit_price": exit_price,
                    "exit_time": exit_time,
                    "close_reason": row["close_reason"],
                    "gross_pnl_pct": round(gross, 6),
                    "net_pnl_pct": PaperTradeService.net_profit_pct(
                        entry_price, exit_price, None, direction
                    ),
                }
            )
        else:
            # OPEN paper trade: no over-normalization — exit fields stay NULL.
            staged.append({**base, "status": STATUS_OPEN})
        report["paper_inserted"] += 1

    # ---- SHADOW closed (CSV) ----------------------------------------------
    for i, row in enumerate(_shadow_csv_rows(shadow_path, limit), start=1):
        report["shadow_seen"] += 1
        report["shadow_csv_seen"] += 1
        identifier = f"shadow_csv#{i}"
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        entry_price = _parse_float(row.get("entry_price"))
        if entry_price is None or entry_price <= 0:
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        entry_time = aware_utc(row.get("entry_time"))
        if entry_time is None:
            quarantine("shadow", identifier, REASON_INVALID_TIMESTAMP)
            continue
        status, signal_id, matched_type = _match_signal(signal_index, ticker, entry_time, None)
        report[SIGNAL_STAT_KEYS[status]] += 1
        if status in ("exact", "tolerance"):
            signal_type = matched_type
        else:
            signal_type = SignalType.RADAR.value
            report["signal_type_fallbacks"] += 1
        if _is_blank(row.get("exit_price")):
            quarantine("shadow", identifier, REASON_MISSING_EXIT_PRICE)
            continue
        exit_price = _parse_float(row.get("exit_price"))
        if exit_price is None or exit_price <= 0:
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        exit_time = aware_utc(row.get("exit_time"))
        if exit_time is None:
            reason = (
                REASON_INVALID_TIMESTAMP
                if not _is_blank(row.get("exit_time"))
                else REASON_MISSING_EXIT_TIME
            )
            quarantine("shadow", identifier, reason)
            continue
        pnl_pct = _parse_float(row.get("pnl_pct"))
        if pnl_pct is None:
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        key = (ticker, entry_time.isoformat(), exit_time.isoformat())
        if key in keys["shadow_closed"]:
            report["shadow_skipped_existing"] += 1
            continue
        staged.append(
            {
                "kind": KIND_SHADOW,
                "ticker": ticker,
                "signal_type": signal_type,
                "direction": "long",
                "score": _parse_float(row.get("score")),
                "regime": None,
                "entry_price": entry_price,
                "entry_time": entry_time,
                "stop_loss": None,
                "target_price": None,
                "agreement_ratio": _parse_float(row.get("agreement_ratio")),
                "status": STATUS_CLOSED,
                "exit_price": exit_price,
                "exit_time": exit_time,
                "close_reason": (row.get("hit") or "").strip() or None,
                "gross_pnl_pct": pnl_pct,
                "net_pnl_pct": None,
                "paper_trade_id": None,
                "signal_id": signal_id,
                "source": SOURCE_BACKFILL,
            }
        )
        report["shadow_inserted"] += 1
        report["shadow_csv_inserted"] += 1

    # ---- SHADOW open (JSON state) ------------------------------------------
    for ticker_key, entry in _shadow_open_items(shadow_path, limit):
        report["shadow_seen"] += 1
        report["shadow_open_seen"] += 1
        identifier = f"shadow_open#{ticker_key}"
        if not isinstance(entry, dict):
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        ticker = str(entry.get("ticker") or ticker_key or "").strip()
        if not ticker:
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        entry_price = _parse_float(entry.get("entry_price"))
        if entry_price is None or entry_price <= 0:
            quarantine("shadow", identifier, REASON_INVALID_ROW)
            continue
        entry_time = aware_utc(entry.get("entry_time"))
        if entry_time is None:
            quarantine("shadow", identifier, REASON_INVALID_TIMESTAMP)
            continue
        status, signal_id, matched_type = _match_signal(signal_index, ticker, entry_time, None)
        report[SIGNAL_STAT_KEYS[status]] += 1
        if status in ("exact", "tolerance"):
            signal_type = matched_type
        else:
            signal_type = SignalType.RADAR.value
            report["signal_type_fallbacks"] += 1
        open_key = (ticker, entry_time.isoformat())
        if open_key in keys["shadow_open"]:
            report["shadow_skipped_existing"] += 1
            continue
        staged.append(
            {
                "kind": KIND_SHADOW,
                "ticker": ticker,
                "signal_type": signal_type,
                "direction": "long",
                "score": _parse_float(entry.get("score")),
                "regime": None,
                "entry_price": entry_price,
                "entry_time": entry_time,
                "stop_loss": _parse_float(entry.get("stop")),
                "target_price": _parse_float(entry.get("target")),
                "agreement_ratio": _parse_float(entry.get("agreement_ratio")),
                "status": STATUS_OPEN,
                "paper_trade_id": None,
                "signal_id": signal_id,
                "source": SOURCE_BACKFILL,
            }
        )
        report["shadow_inserted"] += 1
        report["shadow_open_inserted"] += 1

    report["total_skipped"] = report["paper_skipped_existing"] + report["shadow_skipped_existing"]
    report["total_quarantined"] = report["paper_quarantined"] + report["shadow_quarantined"]

    if apply and staged:
        TradeLedgerRecord.__table__.create(engine, checkfirst=True)
        now = datetime.now(UTC)
        rows = [
            {**{field: row.get(field) for field in LEDGER_FIELDS}, "created_at": now}
            for row in staged
        ]
        with engine.begin() as conn:
            conn.execute(sa.insert(TradeLedgerRecord), rows)
        report["total_inserted"] = len(staged)
    return report


def _build_engine(db_url: str | None) -> Engine:
    if db_url:
        return sa.create_engine(db_url)
    from bist_bot.config.settings import settings

    url = getattr(settings, "DATABASE_URL", "") or "sqlite:///bist_signals.db"
    return sa.create_engine(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="dry-run yerine gercek yazim yap")
    parser.add_argument("--db", default=None, help="SQLAlchemy URL (default: DATABASE_URL)")
    parser.add_argument(
        "--shadow-dir", default="results", help="shadow_pnl.csv / shadow_open.json dizini"
    )
    parser.add_argument("--limit", type=int, default=None, help="kaynak basina aday limiti")
    args = parser.parse_args()

    engine = _build_engine(args.db)
    report = run_backfill(engine, shadow_dir=args.shadow_dir, apply=args.apply, limit=args.limit)

    print("== TRADE LEDGER BACKFILL ==")
    print(f"  mod: {'APPLY' if args.apply else 'DRY-RUN'}")
    print("== PAPER ==")
    print(
        f"  aday: {report['paper_seen']} | insert edilecek: {report['paper_inserted']} | "
        f"mevcut (skip): {report['paper_skipped_existing']} | quarantine: {report['paper_quarantined']}"
    )
    print("== SHADOW ==")
    print(
        f"  csv aday: {report['shadow_csv_seen']} | insert edilecek: {report['shadow_csv_inserted']}"
    )
    print(
        f"  open aday: {report['shadow_open_seen']} | insert edilecek: {report['shadow_open_inserted']}"
    )
    print(
        f"  toplam mevcut (skip): {report['shadow_skipped_existing']} | "
        f"quarantine: {report['shadow_quarantined']}"
    )
    print("== SIGNAL JOIN ==")
    print(
        f"  birebir: {report['signal_exact_matches']} | "
        f"tolerans(+/-5dk): {report['signal_tolerance_matches']} | "
        f"eslesmedi: {report['signal_unmatched']} | "
        f"ambiguous: {report['signal_ambiguous']} | "
        f"radar fallback: {report['signal_type_fallbacks']}"
    )
    print("== TOPLAM ==")
    print(
        f"  insert: {report['total_inserted']} | skip: {report['total_skipped']} | "
        f"quarantine: {report['total_quarantined']}"
    )
    details = report["quarantine_details"]
    if details:
        print("== QUARANTINE (ilk 20) ==")
        for item in details[:20]:
            print(f"  [{item['source_identifier']}] {item['reason']}")
        for reason, count in sorted(report["quarantine_reasons"].items()):
            print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
