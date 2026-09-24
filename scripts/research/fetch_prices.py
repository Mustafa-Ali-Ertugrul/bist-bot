"""Download daily prices for every point-in-time BIST100 member + XU100 index.

Writes ``close.parquet`` / ``volume.parquet`` into RESEARCH_CACHE
(default ``tmp/research_cache``). Yahoo rate-limits bursts, so tickers are
fetched one by one with retries and the cache is saved after every ticker;
re-running only fetches what is still missing.

Usage:
    python scripts/research/fetch_prices.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(os.environ.get("RESEARCH_CACHE", "tmp/research_cache"))
PIT_FILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bist_bot"
    / "data"
    / "universe"
    / "bist100_pit_quarterly.json"
)
START, END = "2010-01-01", None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    quarters = json.loads(PIT_FILE.read_text(encoding="utf-8"))["quarters"]
    tickers = [*sorted(set().union(*quarters.values())), "XU100.IS"]
    close_path, vol_path = OUT / "close.parquet", OUT / "volume.parquet"
    close = pd.read_parquet(close_path) if close_path.exists() else pd.DataFrame()
    volume = pd.read_parquet(vol_path) if vol_path.exists() else pd.DataFrame()
    todo = [t for t in tickers if t not in close.columns or close[t].dropna().empty]
    print(f"{len(todo)} tickers to fetch", flush=True)
    for _ in range(3):
        failed = []
        for t in todo:
            try:
                d = yf.Ticker(t).history(start=START, end=END, auto_adjust=True)
            except Exception:
                d = None
            if d is None or d.empty:
                failed.append(t)
                time.sleep(2)
                continue
            d.index = d.index.tz_localize(None).normalize()
            d = d[~d.index.duplicated()]
            close = close.reindex(close.index.union(d.index))
            volume = volume.reindex(close.index)
            close[t] = d["Close"].reindex(close.index)
            volume[t] = d["Volume"].reindex(close.index)
            close.to_parquet(close_path)
            volume.to_parquet(vol_path)
            print("ok", t, flush=True)
            time.sleep(0.7)
        todo = failed
        if not todo:
            break
        time.sleep(30)
    # Merged/delisted codes (e.g. ANACM/SODA/TRKCM -> SISE in 2020) have no history.
    print("no data:", todo, flush=True)


if __name__ == "__main__":
    main()
