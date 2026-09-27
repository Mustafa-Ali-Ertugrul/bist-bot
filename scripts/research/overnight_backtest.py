"""Overnight (close -> next open) rules O1-O3 of OVERNIGHT_PREREGISTRATION.md.

Downloads Yahoo daily OHLCV for every point-in-time BIST100 member since 2023
into RESEARCH_CACHE/overnight_ohlcv.parquet (re-used on later runs), then
reports the pre-registered rules on the development and holdout periods.

Usage (from scripts/research):
    python overnight_backtest.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import portfolio_research as pr
import yfinance as yf

OUT = Path(os.environ.get("RESEARCH_CACHE", "../../tmp/research_cache"))
CACHE = OUT / "overnight_ohlcv.parquet"
PIT_FILE = Path(__file__).resolve().parents[2] / "src/bist_bot/data/universe/bist100_pit_quarterly.json"
DEV = ("2023-09-01", "2025-06-30")
HOLDOUT = ("2025-07-01", "2026-09-25")
LIQ_N, TOP_N = 50, 10
COST_BASE, COST_STRESS = 0.0005, 0.0010  # per side
ARTIFACT = 0.25

quarters: dict[str, list[str]] = json.loads(PIT_FILE.read_text(encoding="utf-8"))["quarters"]
qstarts = sorted(quarters)


def members_at(day: pd.Timestamp) -> list[str]:
    return quarters[max(s for s in qstarts if pd.Timestamp(s) <= day)]


def load() -> dict[str, pd.DataFrame]:
    if CACHE.exists():
        df = pd.read_parquet(CACHE)
    else:
        tickers = sorted({t for s in qstarts if s >= "2023-01-01" for t in quarters[s]})
        frames = []
        for i in range(0, len(tickers), 25):
            d = yf.download(tickers[i : i + 25], start="2023-03-01", end="2026-09-27",
                            auto_adjust=False, group_by="ticker", progress=False)
            for t in tickers[i : i + 25]:
                if t in d.columns.get_level_values(0):
                    f = d[t][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    frames.append(f.assign(ticker=t))
            time.sleep(2)
        df = pd.concat(frames).rename_axis("date").reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        OUT.mkdir(parents=True, exist_ok=True)
        df.to_parquet(CACHE)
        print(f"downloaded {df.ticker.nunique()}/{len(tickers)} PIT members")
    return {c: df.pivot(index="date", columns="ticker", values=c) for c in ["Open", "High", "Low", "Close", "Volume"]}


def money_market(days: pd.DatetimeIndex) -> pd.Series:
    """Proxy return from each trading day's close to the next one (calendar days)."""
    s = pd.Series({pd.Timestamp(d): r for d, r in pr.POLICY}).sort_index()
    rate = s.reindex(days.union(s.index)).ffill().reindex(days) / 100 * pr.CASH_NET
    gap = pd.Series(days, index=days).diff().shift(-1).dt.days
    return (1 + rate) ** (gap / 365) - 1


def run() -> pd.DataFrame:
    p = load()
    o, h, l, c, v = p["Open"], p["High"], p["Low"], p["Close"], p["Volume"]
    days = c.index
    night = o.shift(-1) / c - 1  # close t -> open t+1
    bad = (night.abs() > ARTIFACT) | (c.pct_change(fill_method=None).abs() > ARTIFACT)
    night = night.mask(bad)
    intraday = c / o - 1
    rng = (h - l).replace(0, np.nan)
    clv = (c - l) / rng
    tv = (c * v).rolling(60, min_periods=40).median()
    mm = money_market(days)
    rows = []
    for t in days[days >= pd.Timestamp(DEV[0])][:-1]:
        mem = [m for m in members_at(t) if m in c.columns]
        liq = tv.loc[t, mem].dropna().nlargest(LIQ_N).index
        ok = [x for x in liq if pd.notna(night.loc[t, x])]
        if len(ok) < 20:
            continue
        picks = {
            "O1": ok,
            "O2": intraday.loc[t, ok].dropna().nsmallest(TOP_N).index,
            "O3": clv.loc[t, ok].dropna().nlargest(TOP_N).index,
        }
        row = {"date": t, "mm": mm.loc[t]}
        for k, names in picks.items():
            row[k] = night.loc[t, names].mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


def report(r: pd.DataFrame) -> None:
    for per, (a, b) in {"Geliştirme": DEV, "SAKLI TEST": HOLDOUT}.items():
        x = r.loc[a:b]
        mm_ann = ((1 + x.mm).prod() ** (252 / len(x)) - 1) * 100
        print(f"\n== {per} {a} … {b}  ({len(x)} gece, para piyasası vekili yıllık ~%{mm_ann:.1f})")
        print("kural | brüt/gece | net/gece | net−fon/gece | t | yıllık net | yıllık fon | en kötü gece | maks düşüş | stres net−fon t")
        for k in ["O1", "O2", "O3"]:
            g = x[k]
            net = g - 2 * COST_BASE
            ex = net - x.mm
            ex_s = g - 2 * COST_STRESS - x.mm
            eq = (1 + net).cumprod()
            dd = (eq / eq.cummax() - 1).min()
            ann = (eq.iloc[-1] ** (252 / len(x)) - 1) * 100
            t = ex.mean() / ex.std() * np.sqrt(len(ex))
            ts = ex_s.mean() / ex_s.std() * np.sqrt(len(ex_s))
            print(f"{k}   | {g.mean() * 100:+.3f}% | {net.mean() * 100:+.3f}% | {ex.mean() * 100:+.3f}% | {t:+.2f} | "
                  f"%{ann:.1f} | %{mm_ann:.1f} | {g.min() * 100:+.2f}% ({g.idxmin().date()}) | {dd * 100:.1f}% | {ts:+.2f}")
    print("\nYıllara göre net−fon ortalaması (%/gece, temel maliyet):")
    ex = r[["O1", "O2", "O3"]].sub(2 * COST_BASE).sub(r.mm, axis=0) * 100
    print(ex.groupby(ex.index.year).mean().round(3).to_string())


if __name__ == "__main__":
    report(run())
