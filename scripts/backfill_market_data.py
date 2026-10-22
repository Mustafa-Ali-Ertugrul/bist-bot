"""Faz 1 backfill: fill instruments, daily bars and (optionally) fundamentals.

Runs outside the worker so the Civo process never blocks on a long vendor
crawl. Idempotent: re-running replaces the same (ticker, date) rows.

Usage:
    python scripts/backfill_market_data.py --refresh-universe
    python scripts/backfill_market_data.py --limit 5
    python scripts/backfill_market_data.py --symbols THYAO,GARAN --fundamentals
    python scripts/backfill_market_data.py --start 2016-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.db import DatabaseManager  # noqa: E402
from bist_bot.db.repositories.market_data_repository import MarketDataRepository  # noqa: E402
from bist_bot.services.daily_bar_service import DailyBarService, SyncReport  # noqa: E402


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill stored BIST market data")
    parser.add_argument("--start", help="YYYY-MM-DD (default: DAILY_BARS_START_DATE)")
    parser.add_argument("--end", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--limit", type=int, help="Only the first N active instruments")
    parser.add_argument("--symbols", help="Comma-separated codes (e.g. THYAO,GARAN)")
    parser.add_argument("--fundamentals", action="store_true", help="Also sync statements")
    parser.add_argument(
        "--refresh-universe", action="store_true", help="Only refresh the instrument list"
    )
    parser.add_argument("--workers", type=int, help="Override DAILY_BARS_MAX_WORKERS")
    parser.add_argument("--db-path", help="SQLite path (default: DATABASE_URL/DB_PATH)")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Continue from each ticker's last stored date instead of --start",
    )
    args = parser.parse_args()

    overrides: dict[str, object] = {}
    if args.start:
        overrides["DAILY_BARS_START_DATE"] = args.start
    if args.workers:
        overrides["DAILY_BARS_MAX_WORKERS"] = args.workers
    runtime_settings = settings.replace(**overrides) if overrides else settings

    manager = DatabaseManager(sqlite_path=args.db_path)
    manager.initialize()
    repository = MarketDataRepository(manager)
    service = DailyBarService(repository, runtime_settings)

    if args.refresh_universe:
        print(json.dumps({"universe": service.refresh_universe(force=True)}))
        return 0

    service.refresh_universe(force=True)
    instruments = repository.list_active_instruments()
    if args.symbols:
        wanted = {item.strip().upper().removesuffix(".IS") for item in args.symbols.split(",")}
        instruments = [item for item in instruments if item.code in wanted]
    if args.limit:
        instruments = instruments[: max(0, args.limit)]
    if not instruments:
        print(json.dumps({"error": "no instruments to sync"}))
        return 1

    end = _parse_date(args.end) or date.today()
    configured_start = date.fromisoformat(str(runtime_settings.DAILY_BARS_START_DATE))
    report = SyncReport(as_of=end, symbols=len(instruments))
    started = time.monotonic()
    delay = max(0.0, float(runtime_settings.DAILY_BARS_REQUEST_DELAY_SECONDS))
    workers = max(1, int(runtime_settings.DAILY_BARS_MAX_WORKERS))

    def _one(instrument):
        start = service.dates_for(instrument, as_of=end, full_history=not args.incremental)[0]
        if start > end:
            return 0, None
        try:
            written = service.sync_symbol(instrument, start=start, end=end)
        except Exception as exc:  # keep going; report failures
            return 0, f"{instrument.code}:{type(exc).__name__}"
        finally:
            if delay:
                time.sleep(delay)
        return written, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for written, error in pool.map(_one, instruments):
            if error is not None:
                report.failed += 1
                if len(report.errors) < 10:
                    report.errors.append(error)
                continue
            if written:
                report.written += written
            else:
                report.empty += 1

    if args.fundamentals:
        report.fundamentals = service.sync_fundamentals(instruments, as_of=end)

    report.elapsed_seconds = time.monotonic() - started
    payload = report.as_dict()
    payload["window_start"] = configured_start.isoformat()
    payload["incremental"] = bool(args.incremental)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
