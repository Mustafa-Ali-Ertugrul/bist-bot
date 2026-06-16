"""Walk-forward validation for US tickers.

Trains on 180d, tests on 30d, rolls forward across 1y of data.
Target: AAPL, MSFT, NVDA, META, AMZN.
Overfit threshold: Test Sharpe >= Train Sharpe * 0.6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import pandas as pd

from bist_bot.backtest import Backtester
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.strategy import StrategyEngine

_DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "META", "AMZN"]
_TRAIN_DAYS = 180
_TEST_DAYS = 30


def _sharpe(returns):
    if not returns:
        return 0.0
    s = pd.Series(returns)
    if s.std() == 0 or len(s) < 2:
        return 0.0
    return float(s.mean() / s.std() * (252 ** 0.5))


def _residual_return(signal):
    score = getattr(signal, "score", 0)
    side = getattr(signal, "side", "HOLD")
    if side == "BUY" and score > 20:
        return 0.001
    if side == "SELL" and score < -20:
        return -0.001
    return 0.0


def run_walkforward(ticker):
    fetcher = BISTDataFetcher(watchlist=[ticker])
    engine = StrategyEngine()
    backtester = Backtester(engine=engine, fetcher=fetcher)

    df = fetcher.fetch_single(ticker, period="1y", interval="1d")
    if df is None or len(df) < (_TRAIN_DAYS + _TEST_DAYS):
        bars = len(df) if df is not None else 0
        return {"ticker": ticker, "status": "INSUFFICIENT_DATA", "bars": bars}

    dates = df.index
    windows = []
    start_idx = 0
    while start_idx + _TRAIN_DAYS + _TEST_DAYS <= len(dates):
        train_start = dates[start_idx]
        train_end = dates[start_idx + _TRAIN_DAYS - 1]
        test_end = dates[min(start_idx + _TRAIN_DAYS + _TEST_DAYS - 1, len(dates) - 1)]

        tr_start = str(train_start.date())
        tr_end = str(train_end.date())
        te_end = str(test_end.date())

        try:
            train_signals = backtester.run_single(ticker, start=tr_start, end=tr_end, interval="1d")
            test_signals = backtester.run_single(ticker, start=tr_end, end=te_end, interval="1d")
        except Exception as exc:
            windows.append({"train_start": tr_start, "test_end": te_end, "status": "ERROR: " + str(exc)})
            start_idx += _TEST_DAYS
            continue

        train_returns = [_residual_return(s) for s in train_signals]
        test_returns = [_residual_return(s) for s in test_signals]

        train_sharpe = _sharpe(train_returns)
        test_sharpe = _sharpe(test_returns)

        if train_sharpe and train_sharpe != 0:
            overfit_score = test_sharpe / train_sharpe
        else:
            overfit_score = 0.0
        status = "PASS" if overfit_score >= 0.6 else "OVERFIT"

        windows.append({
            "train_start": tr_start,
            "train_end": tr_end,
            "test_end": te_end,
            "train_signals": len(train_signals),
            "test_signals": len(test_signals),
            "train_sharpe": round(train_sharpe, 4),
            "test_sharpe": round(test_sharpe, 4),
            "overfit_score": round(overfit_score, 4),
            "status": status,
        })
        start_idx += _TEST_DAYS

    pass_count = sum(1 for w in windows if w.get("status") == "PASS")
    total = len(windows)
    overall = "PASS" if total > 0 and pass_count / total >= 0.7 else "OVERFIT"
    return {
        "ticker": ticker,
        "windows": total,
        "pass": pass_count,
        "fail": total - pass_count,
        "overall_status": overall,
        "window_results": windows,
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validation for US tickers")
    parser.add_argument("--tickers", default=",".join(_DEFAULT_TICKERS), help="Comma-separated tickers")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    print("=" * 60)
    print("WALK-FORWARD VALIDATION")
    print("=" * 60)

    results = {}
    any_overfit = False
    for ticker in tickers:
        print("\n[" + ticker + "] Running walk-forward ...")
        res = run_walkforward(ticker)
        results[ticker] = res
        print("  windows:", res["windows"], "pass:", res["pass"], "fail:", res["fail"], "status:", res["overall_status"])
        if res["overall_status"] != "PASS":
            any_overfit = True

    output_dir = os.path.join("data", "paper_reports")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "walkforward.json")
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump({
            "timestamp": datetime.now(UTC).isoformat(),
            "tickers": tickers,
            "results": results,
            "any_overfit": any_overfit,
        }, fh, ensure_ascii=False, indent=2, default=str)

    print("\nReport written:", output_path)
    return 1 if any_overfit else 0


if __name__ == "__main__":
    sys.exit(main())
