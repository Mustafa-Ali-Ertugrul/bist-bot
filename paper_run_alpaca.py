"""Alpaca paper trading runner with smoke test milestone.

Usage:
    python paper_run_alpaca.py --dry-run          # Log orders but don't submit
    python paper_run_alpaca.py                    # Live paper orders
    python paper_run_alpaca.py --smoke-only       # Run smoke tests and exit

Smoke Milestone (required before scheduler):
  1. get_account_info()
  2. fetch_history("AAPL")
  3. fetch_quote("AAPL")
  4. place_limit_order() + cancel_order()

Reports are written to data/paper_reports/ as JSON lines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from bist_bot.config.settings import settings
from bist_bot.execution.alpaca_broker import AlpacaBroker, AlpacaCredentials
from bist_bot.execution.base import OrderSide, OrderType

REPORTS_DIR = Path(__file__).parent / "data" / "paper_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

_WATCHLIST_5 = ["AAPL", "MSFT", "NVDA", "AMZN", "META"]


def _report(title: str, payload: dict) -> None:
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "title": title,
        "payload": payload,
    }
    report_file = REPORTS_DIR / f"{datetime.now(UTC):%Y%m%d}.jsonl"
    with open(report_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _build_broker(dry_run: bool = False) -> AlpacaBroker:
    creds = AlpacaCredentials(
        api_key=settings.ALPACA_API_KEY or os.getenv("ALPACA_API_KEY", ""),
        secret_key=settings.ALPACA_SECRET_KEY or os.getenv("ALPACA_SECRET_KEY", ""),
    )
    paper = settings.ALPACA_PAPER if hasattr(settings, "ALPACA_PAPER") else True
    return AlpacaBroker(credentials=creds, paper=paper, dry_run=dry_run)


def smoke_account(broker: AlpacaBroker) -> dict:
    print("[1/5] get_account_info() ...")
    info = broker.get_account_info()
    result = {
        "cash": info.cash_balance,
        "buying_power": info.buying_power,
        "equity": info.equity,
        "currency": info.currency,
    }
    print(f"    OK: cash={result['cash']}, buying_power={result['buying_power']}, equity={result['equity']}")
    _report("smoke_account", result)
    return result


def smoke_history(broker: AlpacaBroker) -> dict:
    print("[2/5] fetch_history('AAPL') ...")
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(
        broker.credentials.api_key,
        broker.credentials.secret_key,
    )
    request = StockBarsRequest(
        symbol_or_symbols="AAPL",
        timeframe=TimeFrame.Day,
        start=datetime(2024, 1, 1),
        end=datetime(2024, 1, 10),
    )
    bars = client.get_stock_bars(request)
    count = len(bars.data.get("AAPL", [])) if hasattr(bars, "data") else 0
    print(f"    OK: fetched {count} daily bars for AAPL")
    result = {"symbol": "AAPL", "bars_count": count}
    _report("smoke_history", result)
    return result


def smoke_quote(broker: AlpacaBroker) -> dict:
    print("[3/5] fetch_quote('AAPL') ...")
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest

    client = StockHistoricalDataClient(
        broker.credentials.api_key,
        broker.credentials.secret_key,
    )
    request = StockLatestQuoteRequest(symbol_or_symbols="AAPL")
    quote = client.get_stock_latest_quote(request)
    data = quote.data.get("AAPL")
    bid = float(data.bid_price) if data and hasattr(data, "bid_price") else None
    ask = float(data.ask_price) if data and hasattr(data, "ask_price") else None
    print(f"    OK: bid={bid}, ask={ask}")
    result = {"symbol": "AAPL", "bid": bid, "ask": ask}
    _report("smoke_quote", result)
    return result


def smoke_limit_order(broker: AlpacaBroker) -> dict:
    print("[4/5] place_limit_order('AAPL') ...")
    result = broker.place_order(
        ticker="AAPL",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.LIMIT,
        price=1.0,
    )
    print(f"    OK: accepted={result.accepted}, order_id={result.order_id}, state={result.state.value}")
    _report("smoke_limit_order", {"accepted": result.accepted, "order_id": result.order_id})
    return {"order_id": result.order_id, "accepted": result.accepted}


def smoke_cancel(broker: AlpacaBroker, order_id: str) -> dict:
    print("[5/5] cancel_order() ...")
    ok = broker.cancel_order(order_id)
    print(f"    OK: cancelled={ok}")
    result = {"order_id": order_id, "cancelled": ok}
    _report("smoke_cancel", result)
    return result


def run_smoke_tests(dry_run: bool = False) -> bool:
    broker = _build_broker(dry_run=dry_run)
    print("=" * 60)
    print("ALPACA SMOKE TEST MILESTONE")
    print("=" * 60)

    checks = []

    try:
        smoke_account(broker)
        checks.append(("account_info", True))
    except Exception as exc:
        print(f"    FAIL: {exc}")
        checks.append(("account_info", False))

    try:
        smoke_history(broker)
        checks.append(("fetch_history", True))
    except Exception as exc:
        print(f"    FAIL: {exc}")
        checks.append(("fetch_history", False))

    try:
        smoke_quote(broker)
        checks.append(("fetch_quote", True))
    except Exception as exc:
        print(f"    FAIL: {exc}")
        checks.append(("fetch_quote", False))

    order_id = None
    try:
        res = smoke_limit_order(broker)
        order_id = res.get("order_id")
        checks.append(("place_limit_order", True))
    except Exception as exc:
        print(f"    FAIL: {exc}")
        checks.append(("place_limit_order", False))

    if order_id:
        try:
            smoke_cancel(broker, order_id)
            checks.append(("cancel_order", True))
        except Exception as exc:
            print(f"    FAIL: {exc}")
            checks.append(("cancel_order", False))
    else:
        checks.append(("cancel_order", False))

    print("\n" + "=" * 60)
    print("SMOKE TEST RESULTS")
    print("=" * 60)
    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_pass = False

    _report("smoke_summary", {"all_pass": all_pass, "checks": {n: v for n, v in checks}})

    if all_pass:
        print("\nALL SMOKE CHECKS PASSED. Ready for scheduler.")
    else:
        print("\nSOME SMOKE CHECKS FAILED. Fix before scheduler.")
    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Alpaca paper trading runner")
    parser.add_argument("--dry-run", action="store_true", help="Log orders but do not submit to Alpaca")
    parser.add_argument("--smoke-only", action="store_true", help="Run smoke tests and exit")
    args = parser.parse_args()

    # Ensure we have credentials before anything else
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        print("ERROR: Missing ALPACA_API_KEY or ALPACA_SECRET_KEY")
        sys.exit(1)

    if args.smoke_only:
        ok = run_smoke_tests(dry_run=args.dry_run)
        sys.exit(0 if ok else 1)

    # TODO: Implement full paper trading loop once milestone passes
    print("Dry-run / full trading loop not yet implemented.")
    print("Run with --smoke-only to validate connectivity first.")


if __name__ == "__main__":
    main()
