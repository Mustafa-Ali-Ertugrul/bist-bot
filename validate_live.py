"""Live validation: collect_scan_result now persists scan_log to DB.

Runs a real scan with yfinance on a small ticker subset,
then verifies /api/stats latest_scan is populated.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "validation_test.db")
os.environ["DB_PATH"] = _db_path
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

from bist_bot.contracts import SilentNotifier
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.db.access import DataAccess
from bist_bot.strategy.engine import StrategyEngine
from bist_bot.ui.runtime_scan import collect_scan_result


def main():
    print("=" * 60)
    print("LIVE VALIDATION: collect_scan_result scan_log persistence")
    print("=" * 60)

    db = DataAccess()

    test_tickers = ["THYAO.IS", "GARAN.IS", "ASELS.IS", "SISE.IS", "EREGL.IS"]
    fetcher = BISTDataFetcher(watchlist=test_tickers)
    engine = StrategyEngine()
    notifier = SilentNotifier()

    print(f"\n[1] Test tickers: {test_tickers}")
    print(f"    Watchlist size: {len(fetcher.watchlist)}")

    before = db.get_latest_scan_log()
    print(f"\n[2] DB latest_scan BEFORE scan: {before}")

    print("\n[3] Running collect_scan_result (real yfinance fetch)...")
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

    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)

    checks = []

    check1 = after is not None
    checks.append(("latest_scan exists in DB", check1))

    if after:
        check2 = after.get("total_scanned", 0) > 0
        checks.append(("total_scanned > 0", check2))

        check3 = after.get("total_scanned") == len(all_data)
        checks.append(
            (f"total_scanned ({after.get('total_scanned')}) == all_data ({len(all_data)})", check3)
        )

        check4 = after.get("signals_generated") == len(signals)
        checks.append(
            (
                f"signals_generated ({after.get('signals_generated')}) == len(signals) ({len(signals)})",
                check4,
            )
        )

        check5 = after.get("actionable", -1) >= 0
        checks.append(("actionable >= 0", check5))

        check6 = after.get("timestamp") is not None
        checks.append(("timestamp is set", check6))

        buys = after.get("buy_signals", 0)
        sells = after.get("sell_signals", 0)
        actionable = after.get("actionable", 0)
        check7 = buys + sells <= actionable
        checks.append(
            (f"buys({buys}) + sells({sells}) <= actionable({actionable})", check7)
        )

        print(f"\n  total_scanned   : {after.get('total_scanned')}")
        print(f"  signals_generated: {after.get('signals_generated')}")
        print(f"  buy_signals     : {after.get('buy_signals')}")
        print(f"  sell_signals    : {after.get('sell_signals')}")
        print(f"  actionable      : {after.get('actionable')}")
        print(f"  timestamp       : {after.get('timestamp')}")

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


if __name__ == "__main__":
    sys.exit(main())
