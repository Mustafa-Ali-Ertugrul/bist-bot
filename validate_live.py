"""Validate that collect_scan_result persists scan_log records.

The default mode runs a small live yfinance-backed scan. Use ``--mode mock`` for
a deterministic smoke check that does not touch the network.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEST_TICKERS = ["THYAO.IS", "GARAN.IS", "ASELS.IS", "SISE.IS", "EREGL.IS"]


@dataclass(frozen=True)
class ValidationConfig:
    mode: str
    db_path: Path
    keep_db: bool
    created_temp_db: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate collect_scan_result scan_log persistence."
    )
    parser.add_argument(
        "--mode",
        choices=("live", "mock"),
        default="live",
        help="Use live yfinance data or deterministic mocked data.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite DB path for validation. Defaults to a temp file.",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep the validation DB after the run for inspection.",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> ValidationConfig:
    if args.db_path is not None:
        db_path = args.db_path.expanduser().resolve()
        created_temp_db = False
    else:
        fd, name = tempfile.mkstemp(prefix="bist_bot_validate_", suffix=".db")
        os.close(fd)
        db_path = Path(name).resolve()
        created_temp_db = True
    return ValidationConfig(
        mode=args.mode,
        db_path=db_path,
        keep_db=args.keep_db,
        created_temp_db=created_temp_db,
    )


def configure_environment(db_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(db_path)
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"


def cleanup_database(db_path: Path, keep_db: bool) -> None:
    if keep_db:
        print(f"\nValidation DB kept at: {db_path}")
        return
    candidates = (
        db_path,
        db_path.with_suffix(db_path.suffix + "-wal"),
        db_path.with_suffix(db_path.suffix + "-shm"),
    )
    for candidate in candidates:
        try:
            candidate.unlink(missing_ok=True)
        except OSError as exc:
            print(
                f"WARNING: could not remove {candidate}: "
                f"{type(exc).__name__} errno={getattr(exc, 'errno', 'unknown')}"
            )


class MockFetcher:
    watchlist = TEST_TICKERS

    def clear_cache(
        self,
        scope: str = "all",
        ticker: str | None = None,
        period: str | None = None,
        interval: str | None = None,
    ) -> None:
        return None

    def fetch_multi_timeframe_all(
        self,
        trend_period: str = "6mo",
        trend_interval: str = "1d",
        trigger_period: str = "1mo",
        trigger_interval: str = "15m",
        force_refresh: bool = False,
    ) -> dict[str, dict[str, Any]]:
        return self.fetch_multi_timeframe(TEST_TICKERS)

    def fetch_multi_timeframe(
        self,
        tickers: list[str],
        trend_period: str = "6mo",
        trend_interval: str = "1d",
        trigger_period: str = "1mo",
        trigger_interval: str = "15m",
        force_refresh: bool = False,
    ) -> dict[str, dict[str, Any]]:
        import pandas as pd

        frame = pd.DataFrame(
            {
                "Close": [100.0, 101.5, 103.0],
                "High": [101.0, 102.0, 104.0],
                "Low": [99.0, 100.5, 102.5],
                "Volume": [1000, 1100, 1300],
            }
        )
        return {ticker: {"trend": frame, "trigger": frame} for ticker in tickers}


class MockEngine:
    def __init__(self) -> None:
        from bist_bot.strategy.signal_models import Signal, SignalType

        self._signals = [
            Signal(
                ticker="THYAO.IS",
                signal_type=SignalType.BUY,
                score=25.0,
                price=103.0,
                reasons=["mock.validation"],
            )
        ]

    def scan_all(self, data: dict[str, Any]) -> list[Any]:
        return list(self._signals)

    def analyze(
        self,
        ticker: str,
        df: Any,
        enforce_sector_limit: bool = False,
    ) -> Any | None:
        if ticker == self._signals[0].ticker:
            return self._signals[0]
        return None

    def get_last_rejection_breakdown(self) -> dict[str, Any]:
        return {
            "total_rejections": 0,
            "by_reason": [],
            "by_stage": [],
            "scan_id": "validate-live-mock",
        }


def build_dependencies(mode: str) -> tuple[Any, Any, Any, Any]:
    from bist_bot.contracts import SilentNotifier
    from bist_bot.db.access import DataAccess

    db = DataAccess()
    notifier = SilentNotifier()
    if mode == "mock":
        return MockFetcher(), MockEngine(), notifier, db

    from bist_bot.data.fetcher import BISTDataFetcher
    from bist_bot.strategy.engine import StrategyEngine

    return BISTDataFetcher(watchlist=TEST_TICKERS), StrategyEngine(), notifier, db


def dispose_database(db: Any) -> None:
    manager = getattr(db, "manager", None)
    session_factory = getattr(manager, "session_factory", None)
    if session_factory is not None:
        session_factory.remove()
    engine = getattr(manager, "engine", None)
    if engine is not None:
        engine.dispose()


def run_validation(config: ValidationConfig) -> int:
    from bist_bot.ui.runtime_scan import collect_scan_result

    fetcher, engine, notifier, db = build_dependencies(config.mode)

    print("=" * 60)
    print(f"{config.mode.upper()} VALIDATION: collect_scan_result scan_log persistence")
    print("=" * 60)
    print(f"\n[1] Test tickers: {TEST_TICKERS}")
    print(f"    Watchlist size: {len(getattr(fetcher, 'watchlist', TEST_TICKERS))}")
    print(f"    DB path: {config.db_path}")

    try:
        before = db.get_latest_scan_log()
        print(f"\n[2] DB latest_scan BEFORE scan: {before}")

        print(f"\n[3] Running collect_scan_result ({config.mode} mode)...")
        try:
            result = collect_scan_result(
                fetcher=fetcher,
                engine=engine,
                notifier=notifier,
                db=db,
                last_scan_time=None,
                force_clear=False,
            )
        except Exception as exc:
            print(f"    FATAL: collect_scan_result raised: {exc}")
            import traceback

            traceback.print_exc()
            return 1

        signals = result.get("signals", [])
        all_data = result.get("all_data", {})
        error = result.get("error")

        print(f"    Error: {error}")
        print(f"    all_data keys: {len(all_data)} tickers")
        print(f"    Signals: {len(signals)} total")

        if error:
            print(f"\n    Scan returned error: {error}")
            print("    Checking DB anyway...")

        after = db.get_latest_scan_log()
        print(f"\n[4] DB latest_scan AFTER scan: {after}")
        return print_results(after, all_data, signals)
    finally:
        dispose_database(db)


def print_results(after: dict[str, Any] | None, all_data: dict[str, Any], signals: list[Any]) -> int:
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)

    checks: list[tuple[str, bool]] = [("latest_scan exists in DB", after is not None)]

    if after:
        checks.extend(
            [
                ("total_scanned > 0", after.get("total_scanned", 0) > 0),
                (
                    f"total_scanned ({after.get('total_scanned')}) == all_data ({len(all_data)})",
                    after.get("total_scanned") == len(all_data),
                ),
                (
                    f"signals_generated ({after.get('signals_generated')}) == len(signals) ({len(signals)})",
                    after.get("signals_generated") == len(signals),
                ),
                ("actionable >= 0", after.get("actionable", -1) >= 0),
                ("timestamp is set", after.get("timestamp") is not None),
            ]
        )

        buys = after.get("buy_signals", 0)
        sells = after.get("sell_signals", 0)
        actionable = after.get("actionable", 0)
        checks.append((f"buys({buys}) + sells({sells}) <= actionable({actionable})", buys + sells <= actionable))

        print(f"\n  total_scanned    : {after.get('total_scanned')}")
        print(f"  signals_generated: {after.get('signals_generated')}")
        print(f"  buy_signals      : {after.get('buy_signals')}")
        print(f"  sell_signals     : {after.get('sell_signals')}")
        print(f"  actionable       : {after.get('actionable')}")
        print(f"  timestamp        : {after.get('timestamp')}")

    all_pass = all(ok for _, ok in checks)
    print()
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")

    print()
    if all_pass:
        print("ALL CHECKS PASSED - scan_log persistence is working.")
        print("/api/stats -> latest_scan will now update after UI scans.")
    else:
        print("SOME CHECKS FAILED - investigate above.")

    return 0 if all_pass else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_config(args)
    configure_environment(config.db_path)
    try:
        return run_validation(config)
    finally:
        cleanup_database(config.db_path, config.keep_db)


if __name__ == "__main__":
    sys.exit(main())
