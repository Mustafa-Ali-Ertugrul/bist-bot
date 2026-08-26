"""One-off import: merge legacy SQLite files into the shared PostgreSQL store.

Used after switching the Docker stack from per-container SQLite files to the
shared Postgres database. Reads ``signals``, ``paper_trades``, ``scan_log``
and ``app_settings`` rows from one or more SQLite files and inserts them into
the active DATABASE_URL target, skipping duplicates.

Usage (inside the api container):
    python /tmp/import_sqlite_to_postgres.py /tmp/worker_signals.db /tmp/host_signals.db

Safety: additive only — never updates or deletes existing target rows.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, column, create_engine, inspect, select, table

from bist_bot.db.connection import resolve_database_url

DATETIME_COLUMNS = {
    "signals": {"timestamp", "created_at", "outcome_date", "expires_at"},
    "paper_trades": {"signal_time", "exit_date", "close_time"},
    "scan_log": {"timestamp"},
    "app_settings": {"updated_at"},
}

DEDUPE_KEYS = {
    "signals": ("ticker", "signal_type", "timestamp"),
    "paper_trades": ("ticker", "signal_type", "signal_price", "signal_time"),
    "scan_log": ("timestamp", "scan_id"),
    "app_settings": ("key",),
}


def _parse_dt(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _coerce_row(row: dict[str, Any], dt_columns: set[str]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for column, value in row.items():
        if column in dt_columns:
            coerced[column] = _parse_dt(value)
        elif isinstance(value, str) and value.strip() == "" and column not in {
            "reasons",
            "conditions",
            "rejection_breakdown",
            "score_breakdown",
            "metadata_json",
            "value",
        }:
            coerced[column] = None
        else:
            coerced[column] = value
    return coerced


def _dedupe_key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple:
    parts: list[Any] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, datetime):
            value = value.isoformat()
        parts.append(value)
    return tuple(parts)


def import_table(
    src_conn: sqlite3.Connection,
    target_engine,
    table_name: str,
    seen: set[tuple],
) -> tuple[int, int]:
    dt_columns = DATETIME_COLUMNS[table_name]
    keys = DEDUPE_KEYS[table_name]

    src_rows = [
        dict(row)
        for row in src_conn.execute(f"SELECT * FROM {table_name}")  # noqa: S608
    ]
    if not src_rows:
        return 0, 0

    src_columns = {column[1] for column in src_conn.execute(f"PRAGMA table_info({table_name})")}

    inspector = inspect(target_engine)
    target_columns = {col["name"] for col in inspector.get_columns(table_name)}
    columns = sorted((src_columns & target_columns) - {"id"})
    core_table = table(table_name, *[Column(name) for name in columns])

    selectable = select(*[column(name) for name in keys]).select_from(core_table)
    existing = set()
    with target_engine.connect() as conn:
        for existing_row in conn.execute(selectable):
            row_dict = dict(existing_row._mapping)
            for key_name, value in list(row_dict.items()):
                if isinstance(value, datetime):
                    row_dict[key_name] = value.isoformat()
            existing.add(tuple(row_dict.get(k) for k in keys))

    to_insert: list[dict[str, Any]] = []
    skipped = 0
    for raw_row in src_rows:
        row = _coerce_row(raw_row, dt_columns)
        row = {column: value for column, value in row.items() if column in columns}
        key = _dedupe_key(row, keys)
        if key in existing or key in seen:
            skipped += 1
            continue
        seen.add(key)
        to_insert.append(row)

    inserted = 0
    with target_engine.begin() as conn:
        for start in range(0, len(to_insert), 100):
            chunk = to_insert[start : start + 100]
            conn.execute(core_table.insert(), chunk)
            inserted += len(chunk)
    return inserted, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", help="SQLite files to import from, in priority order")
    parser.add_argument(
        "--tables",
        default="signals,paper_trades,scan_log,app_settings",
        help="Comma-separated list of tables to import",
    )
    args = parser.parse_args()

    config = resolve_database_url()
    if config.is_sqlite:
        print("ERROR: DATABASE_URL resolves to SQLite; refusing to import into itself.")
        return 1
    engine = create_engine(config.url, future=True)

    tables = [name.strip() for name in args.tables.split(",") if name.strip()]
    totals: dict[str, list[int]] = {name: [0, 0] for name in tables}
    seen: dict[str, set[tuple]] = {name: set() for name in tables}

    for source in args.sources:
        source_path = Path(source)
        if not source_path.exists():
            print(f"skip missing source: {source_path}")
            continue
        print(f"importing from {source_path.name} ...")
        src_conn = sqlite3.connect(str(source_path))
        src_conn.row_factory = sqlite3.Row
        for table_name in tables:
            try:
                inserted, skipped = import_table(src_conn, engine, table_name, seen[table_name])
            except sqlite3.OperationalError as exc:
                print(f"  {table_name}: source unavailable ({exc})")
                continue
            totals[table_name][0] += inserted
            totals[table_name][1] += skipped
            print(f"  {table_name}: +{inserted} inserted, {skipped} duplicates skipped")
        src_conn.close()

    print("\nTotal:", ", ".join(f"{name}={c[0]} (dup {c[1]})" for name, c in totals.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
