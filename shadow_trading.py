"""Shadow trading runner: scan -> signal -> risk check -> log, no real orders.

Usage:
    python shadow_trading.py --symbols AAPL,MSFT,NVDA,META,AMZN --runs 7
    python shadow_trading.py --symbols AAPL,MSFT --runs 1 --dry-run

Emulates the full pipeline but never calls broker.submit_order().
Every would-be order is logged as JSON for later analysis.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.reports.daily_report import generate_daily_report
from bist_bot.risk.portfolio_limits import (
    PortfolioLimits,
    PortfolioState,
    check_order_against_limits,
)
from bist_bot.strategy import StrategyEngine
from bist_bot.strategy.signal_models import SignalType

logger = get_logger(__name__, component="shadow_trading")
REPORTS_DIR = Path("data") / "paper_reports" / "shadow"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "META", "AMZN"]
_MIN_SCORE = 8


def _log_shadow_order(payload: dict) -> None:
    # timestamp embedded in jsonl
    file_path = REPORTS_DIR / f"shadow_{datetime.now(UTC):%Y%m%d}.jsonl"
    with open(file_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _prepare_portfolio_state(cash: float = 100000.0) -> PortfolioState:
    return PortfolioState(equity=cash, cash=cash, peak_equity=cash)


def run_shadow_scan(
    symbols: list[str],
    cash: float = 100000.0,
    dry_run: bool = False,
) -> dict:
    fetcher = BISTDataFetcher(watchlist=symbols)
    engine = StrategyEngine()
    state = _prepare_portfolio_state(cash)
    limits = PortfolioLimits(
        MAX_OPEN_POSITIONS=settings.MAX_OPEN_POSITIONS if hasattr(settings, "MAX_OPEN_POSITIONS") else 5,
        MAX_POSITION_SIZE=settings.MAX_POSITION_SIZE if hasattr(settings, "MAX_POSITION_SIZE") else 0.20,
        MAX_DAILY_LOSS=settings.MAX_DAILY_LOSS if hasattr(settings, "MAX_DAILY_LOSS") else 0.03,
        MAX_ACCOUNT_DRAWDOWN=settings.MAX_ACCOUNT_DRAWDOWN if hasattr(settings, "MAX_ACCOUNT_DRAWDOWN") else 0.15,
    )

    logger.info("shadow_scan_start", symbols=symbols, cash=cash, dry_run=dry_run)
    print("=" * 60)
    print("SHADOW TRADING SCAN")
    print("=" * 60)
    print("Symbols:", ", ".join(symbols))
    print("Cash:    ", cash)
    print("Dry-run: ", dry_run)

    try:
        data = fetcher.fetch_all(period="3mo", interval="1d")
    except Exception as exc:
        logger.error("shadow_fetch_failed", error=str(exc))
        print("FATAL: fetch_all failed:", exc)
        return {"status": "FETCH_FAILED", "error": str(exc)}

    signals = engine.scan_all(data)
    actionable = engine.get_actionable_signals(signals)

    print(f"\nTotal signals: {len(signals)}")
    print(f"Actionable:    {len(actionable)}")

    shadow_records = []
    blocked_records = []

    for sig in actionable:
        symbol = sig.ticker
        side = "BUY" if sig.signal_type in {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY} else "SELL"
        score = getattr(sig, "score", 0)
        price = getattr(sig, "close_price", 0.0) or 0.0

        quantity = 1.0
        if price > 0:
            quantity = round(cash * limits.MAX_POSITION_SIZE / price, 2)

        check = check_order_against_limits(symbol, side, quantity, price, state, limits)

        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "symbol": symbol,
            "signal": side,
            "score": score,
            "price": price,
            "quantity": quantity,
            "notional": round(quantity * price, 2),
            "would_execute": check.allowed,
            "blocked_by": check.blocked_by,
            "reason": check.reason,
        }
        shadow_records.append(record)
        _log_shadow_order(record)

        if check.allowed:
            print(f"  [SHADOW] {symbol} {side} @ {price}  qty={quantity}  score={score}")
            if not dry_run:
                state.open_positions.append({"symbol": symbol, "quantity": quantity, "price": price, "side": side})
        else:
            blocked_records.append(record)
            print(f"  [BLOCK]  {symbol} {side} @ {price}  reason={check.reason}")

    report = generate_daily_report(
        account_info={"equity": state.equity, "yesterday_equity": state.equity},
        closed_trades=[],
        open_positions=state.open_positions,
    )

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "symbols": symbols,
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "shadow_orders": len([r for r in shadow_records if r["would_execute"]]),
        "blocked_orders": len(blocked_records),
        "dry_run": dry_run,
        "report": report,
    }

    summary_path = REPORTS_DIR / f"summary_{datetime.now(UTC):%Y%m%d}.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print("SHADOW SUMMARY")
    print(f"Shadow orders: {summary['shadow_orders']}")
    print(f"Blocked:       {summary['blocked_orders']}")
    print(f"Report:        {summary_path}")
    logger.info("shadow_scan_end", summary=summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow trading runner (no real orders)")
    parser.add_argument("--symbols", default=",".join(_DEFAULT_SYMBOLS), help="Comma-separated symbols")
    parser.add_argument("--runs", type=int, default=7, help="Number of daily runs to simulate")
    parser.add_argument("--cash", type=float, default=100000.0, help="Starting cash")
    parser.add_argument("--dry-run", action="store_true", help="Skip portfolio state mutation")
    parser.add_argument("--interval-hours", type=float, default=24.0, help="Hours between runs")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    for run in range(1, args.runs + 1):
        print(f"\n{'=' * 60}")
        print(f"SHADOW RUN {run}/{args.runs}")
        print(f"{'=' * 60}")
        run_shadow_scan(symbols, cash=args.cash, dry_run=args.dry_run)
        if run < args.runs:
            sleep_seconds = int(args.interval_hours * 3600)
            print(f"\nSleeping {sleep_seconds}s until next run...")
            time.sleep(sleep_seconds)

    print("\nShadow trading complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
