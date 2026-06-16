"""Backtest vs live runtime signal validation.

Ensures strategy engine produces identical signals in backtest and live modes
for the same historical data. Tolerates ±1 point difference.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from bist_bot.backtest import Backtester
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.strategy import StrategyEngine

_DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "META", "AMZN"]


def validate_ticker(ticker: str) -> tuple[str, list[dict]]:
    fetcher = BISTDataFetcher(watchlist=[ticker])
    engine = StrategyEngine()
    backtester = Backtester(engine=engine, fetcher=fetcher)

    # 1. Backtest signal
    back_signals = backtester.run_single(ticker, period="1y", interval="1d")
    back_signal = back_signals[-1] if back_signals else None

    # 2. Live engine signal (same data, same engine)
    df = fetcher.fetch_single(ticker, period="1y", interval="1d")
    live_signal = engine.analyze(ticker, df) if df is not None else None

    if back_signal is None and live_signal is None:
        return ticker, []

    fields = ["score", "signal_type", "side"]
    checks = []
    for field in fields:
        back_val = getattr(back_signal, field, None) if back_signal else None
        live_val = getattr(live_signal, field, None) if live_signal else None
        if field == "score":
            ok = abs((back_val or 0) - (live_val or 0)) <= 1.0
        else:
            ok = back_val == live_val
        checks.append(
            {
                "field": field,
                "backtest": back_val,
                "live": live_val,
                "delta": None if field != "score" else abs((back_val or 0) - (live_val or 0)),
                "status": "PASS" if ok else "FAIL",
            }
        )
    return ticker, checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest vs live signal validator")
    parser.add_argument("--tickers", default=",".join(_DEFAULT_TICKERS), help="Comma-separated tickers")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    print("=" * 60)
    print("BACKTEST vs LIVE VALIDATION")
    print("=" * 60)

    overall_pass = True
    report: dict[str, list[dict]] = {}

    for ticker in tickers:
        print(f"\n[{ticker}] Validating ...")
        t, checks = validate_ticker(ticker)
        report[t] = checks
        for c in checks:
            delta_str = f" (delta={c['delta']:.2f})" if c["delta"] is not None else ""
            print(f"    [{c['status']}] {c['field']}: back={c['backtest']}, live={c['live']}{delta_str}")
            if c["status"] != "PASS":
                overall_pass = False

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    status = "ALL PASS" if overall_pass else "SOME FAILURES"
    print(f"Result: {status}")
    print(f"Tickers checked: {len(report)}")

    # Write report
    report_path = os.path.join("data", "paper_reports", "backtest_vs_live.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "tickers": tickers,
                "overall_pass": overall_pass,
                "results": report,
            },
            fh,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    print(f"Report written: {report_path}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
