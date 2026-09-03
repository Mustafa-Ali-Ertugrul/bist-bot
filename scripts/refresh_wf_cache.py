"""Refresh the walk-forward OHLCV cache for all BIST30 tickers.

Downloads 3y daily OHLCV from Yahoo (via yfinance) and overwrites the parquet
cache used by ``run_walk_forward_bist30.py`` and
``evaluate_july_2026_predictions.py``.

Certificate workaround: this machine's yfinance (curl_cffi) fails with curl
error 77 when the CA bundle lives under OneDrive-synced paths. Pointing
CURL_CA_BUNDLE at a local Temp copy fixes downloads. The variables are set
BEFORE importing yfinance.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMP_CACERT = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "opencode" / "cacert.pem"
if TEMP_CACERT.exists():
    _bundle = str(TEMP_CACERT)
else:
    import certifi

    _bundle = certifi.where()
os.environ["CURL_CA_BUNDLE"] = _bundle
os.environ["REQUESTS_CA_BUNDLE"] = _bundle

import yfinance as yf  # noqa: E402
from run_walk_forward_bist30 import (  # noqa: E402
    BIST30_TICKERS,
    DEFAULT_CACHE_DIR,
    _cache_path,
    _load_tickers_file,
    _normalize_ohlcv,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh BIST30 OHLCV cache")
    parser.add_argument("--period", type=str, default="3y")
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=0, help="First N tickers only (smoke)")
    parser.add_argument("--cache-dir", type=str, default=str(DEFAULT_CACHE_DIR))
    parser.add_argument(
        "--tickers-file",
        type=str,
        default=None,
        help="CSV with a 'ticker' column to use instead of BIST30 (e.g. BIST100).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.tickers_file:
        base_tickers = _load_tickers_file(Path(args.tickers_file))
    else:
        base_tickers = BIST30_TICKERS
    tickers = base_tickers[: args.limit] if args.limit > 0 else base_tickers
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"cert bundle: {_bundle}")
    print(f"cache dir  : {cache_dir}")
    print(f"tickers    : {len(tickers)}  period={args.period}")

    ok = 0
    stale = 0
    failed: list[str] = []
    for idx, ticker in enumerate(tickers, start=1):
        path = _cache_path(cache_dir, ticker, args.period)
        try:
            if args.sleep > 0:
                time.sleep(args.sleep)
            raw = yf.download(ticker, period=args.period, auto_adjust=True, progress=False)
            df = _normalize_ohlcv(raw)
            if df is None or len(df) < 50:
                print(f"[{idx}/{len(tickers)}] {ticker}: EMPTY/SHORT after normalize")
                failed.append(ticker)
                continue
            df.to_parquet(path)
            ok += 1
            print(
                f"[{idx}/{len(tickers)}] {ticker}: rows={len(df)} "
                f"{df.index.min().date()} -> {df.index.max().date()}"
            )
        except Exception as exc:
            print(f"[{idx}/{len(tickers)}] {ticker}: FAILED {type(exc).__name__}: {str(exc)[:120]}")
            failed.append(ticker)

    print("=" * 80)
    print(f"refreshed={ok} failed={len(failed)}")
    if failed:
        print("failed tickers:", ", ".join(failed))
        stale = 1
    return stale


if __name__ == "__main__":
    sys.exit(main())
