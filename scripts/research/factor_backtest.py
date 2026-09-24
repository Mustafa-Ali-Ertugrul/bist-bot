"""Pre-registered fundamental factor test (see FACTOR_PREREGISTRATION.md).

Data: RESEARCH_CACHE/isy (fetch_isyatirim.py) + RESEARCH_CACHE/close.parquet
(XU100 from fetch_prices.py). Run from scripts/research:
    python factor_backtest.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import portfolio_research as pr

ISY = Path(pr.OUT) / "isy"
PIT_FILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bist_bot"
    / "data"
    / "universe"
    / "bist100_pit_quarterly.json"
)
START, DEV_END, HOLDOUT_START = "2016-04-01", "2022-12-31", "2023-01-01"
TOP_N, LIQ_N = 10, 50
COST = pr.COST_STOCK
# Statement for quarter-end month -> first usable date (month, day, year offset).
LAG = {3: (6, 15, 0), 6: (9, 15, 0), 9: (12, 15, 0), 12: (4, 15, 1)}


def load_daily() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    adj, mcap, vol = {}, {}, {}
    for path in sorted(ISY.glob("*_daily.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["HGDG_TARIH"], format="%d-%m-%Y")
        df = df[~df.index.duplicated(keep="last")].sort_index()
        code = path.name.removesuffix("_daily.json") + ".IS"
        adj[code] = pd.to_numeric(df["HGDG_KAPANIS"], errors="coerce")
        mcap[code] = pd.to_numeric(df["PD"], errors="coerce")
        vol[code] = pd.to_numeric(df["HGDG_HACIM"], errors="coerce")
    return pd.DataFrame(adj), pd.DataFrame(mcap), pd.DataFrame(vol)


def load_fundamentals() -> dict[str, pd.DataFrame]:
    """Per ticker: rows indexed by availability date with equity and TTM profit."""
    out = {}
    for path in sorted(ISY.glob("*_fin.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not raw:
            continue
        recs = []
        for key, items in raw.items():
            y, m = (int(x) for x in key.split("/"))
            recs.append(
                {
                    "y": y,
                    "m": m,
                    "eq": items.get("2O"),
                    "ytd": items.get("3Z"),
                    "sales_ytd": items.get("3C"),
                }
            )
        f = pd.DataFrame(recs).set_index(["y", "m"]).sort_index().astype(float)

        def ytd(y, m, f=f, col="ytd"):
            return f[col].get((y, m), np.nan)

        def quarter(y, m, col):
            # Single-quarter value from year-to-date figures (Q1 = YTD).
            return ytd(y, m, col=col) - (ytd(y, m - 3, col=col) if m > 3 else 0.0)

        rows = []
        for y, m in f.index:
            if m == 12:
                ttm = ytd(y, 12)
            else:
                ttm = ytd(y, m) + ytd(y - 1, 12) - ytd(y - 1, m)
            lm, ld, ly = LAG[m]
            rows.append(
                {
                    "avail": pd.Timestamp(date(y + ly, lm, ld)),
                    "equity": f.loc[(y, m), "eq"],
                    "ttm": ttm,
                    "ni_q": quarter(y, m, "ytd"),
                    "ni_q_ly": quarter(y - 1, m, "ytd"),
                    "sales_q": quarter(y, m, "sales_ytd"),
                    "sales_q_ly": quarter(y - 1, m, "sales_ytd"),
                }
            )
        code = path.name.removesuffix("_fin.json") + ".IS"
        out[code] = pd.DataFrame(rows).set_index("avail").sort_index()
    return out


def main() -> None:
    adj_raw, mcap, tvol = load_daily()
    fund = load_fundamentals()
    clean, _, _ = pr.load()
    xu_raw = clean["XU100.IS"]
    idx = adj_raw.index.union(xu_raw.dropna().index)
    ret = adj_raw.reindex(idx).pct_change(fill_method=None)
    ret = ret.mask(ret.abs() > 0.25, 0.0)
    px = (1 + ret.fillna(0)).cumprod().where(adj_raw.reindex(idx).notna()).ffill(limit=5)
    mcap = mcap.reindex(idx).ffill(limit=5)
    tv = tvol.reindex(idx).rolling(60, min_periods=40).median()
    xu = xu_raw.reindex(idx).ffill(limit=5)
    cash_ret = pr.cash_daily(idx)
    cash_eq = (1 + cash_ret).cumprod()
    quarters = json.loads(PIT_FILE.read_text(encoding="utf-8"))["quarters"]
    qstarts = sorted(quarters)

    pos = {d: i for i, d in enumerate(idx)}
    me = [d for d in pr.month_ends(idx) if d >= pd.Timestamp(START)]
    rebals = [d for d in me if pos[d] + 1 < len(idx)]
    execs = [idx[pos[d] + 1] for d in rebals]

    def universe(d):
        q = max(s for s in qstarts if pd.Timestamp(s) <= d)
        mem = [t for t in quarters[q] if t in px.columns]
        hist = px.loc[:d, mem].tail(260).notna().sum()
        ok = hist[hist >= 250].index
        return list(tv.loc[d, ok].dropna().nlargest(LIQ_N).index)

    def fundamentals_at(d, tickers):
        rows = {}
        for t in tickers:
            f = fund.get(t)
            if f is None:
                continue
            f = f.loc[:d]
            if f.empty:
                continue
            last = f.iloc[-1]
            rows[t] = {**last.to_dict(), "mcap": mcap.loc[d, t]}
        return pd.DataFrame(rows).T.astype(float)

    def mom(d, tickers):
        i = pos[d]
        return px.loc[idx[i - 21], tickers] / px.loc[idx[i - 252], tickers] - 1

    def top(score: pd.Series) -> pd.Series:
        s = score.replace([np.inf, -np.inf], np.nan).dropna().nlargest(TOP_N)
        return pd.Series(1 / len(s), index=s.index) if len(s) else pd.Series(dtype=float)

    def signal(name):
        def w(d):
            u = universe(d)
            f = fundamentals_at(d, u)
            if f.empty:
                return pd.Series(dtype=float)
            eq, ttm, mc = f["equity"], f["ttm"], f["mcap"]
            bm = (eq / mc).where(eq > 0)
            ep = (ttm / mc).where(ttm > 0)
            roe = (ttm / eq).where(eq > 0)
            if name == "V1":
                return top(bm)
            if name == "V2":
                return top(ep)
            if name == "Q1":
                return top(roe)
            if name == "C1":
                m = mom(d, list(f.index))
                return top((bm.rank(pct=True) + m.rank(pct=True)) / 2)
            if name == "C2":
                return top((ep.rank(pct=True) + roe.rank(pct=True)) / 2)
            surprise = (f["ni_q"] - f["ni_q_ly"]) / mc
            if name == "E1":
                return top(surprise)
            if name == "E2":
                ok = (f["sales_q"] > 0) & (f["sales_q_ly"] > 0)
                return top((f["sales_q"] / f["sales_q_ly"] - 1).where(ok))
            if name == "E3":
                m = mom(d, list(f.index))
                return top((surprise.rank(pct=True) + m.rank(pct=True)) / 2)
            raise ValueError(name)

        return w

    def ew(d):
        u = universe(d)
        return pd.Series(1 / len(u), index=u) if u else pd.Series(dtype=float)

    ix = xu.to_frame("XU100.IS")
    strategies = {
        "XU100 al-tut": (lambda d: pd.Series({"XU100.IS": 1.0}), ix, pr.COST_INDEX),
        "Para piyasasi": (lambda d: pd.Series(dtype=float), ix, 0.0),
        "Likit50 esit": (ew, px, COST),
        "V1 Defter/Piyasa": (signal("V1"), px, COST),
        "V2 Kar getirisi": (signal("V2"), px, COST),
        "Q1 ROE": (signal("Q1"), px, COST),
        "C1 Deger+Momentum": (signal("C1"), px, COST),
        "C2 Deger+Kalite": (signal("C2"), px, COST),
        "E1 Kar surprizi": (signal("E1"), px, COST),
        "E2 Satis buyumesi": (signal("E2"), px, COST),
        "E3 Surpriz+Momentum": (signal("E3"), px, COST),
    }
    curves = {n: pr.run(fn, p, cash_ret, c, rebals, execs) for n, (fn, p, c) in strategies.items()}
    pd.DataFrame(curves).to_csv(Path(pr.OUT) / "factor_equity.csv")

    pd.set_option("display.width", 250)
    for label, a, b in [
        ("GELISTIRME 2016-04..2022-12", None, DEV_END),
        ("SAKLI TEST 2023-01..2026-09", HOLDOUT_START, None),
        ("TUM DONEM", None, None),
    ]:
        rows = {}
        for n, eq in curves.items():
            e = eq.loc[a:b]
            rows[n] = pr.stats(e / e.iloc[0], cash_eq)
        print(f"\n=== {label} ===")
        print(pd.DataFrame(rows).T.to_string())

    m = pd.DataFrame(curves).pct_change().dropna()
    print("\n=== Aylik XU100 ustu getiri t-istatistigi (tum donem) ===")
    for n in [k for k in curves if k[:2] in ("V1", "V2", "Q1", "C1", "C2", "E1", "E2", "E3")]:
        dlt = m[n] - m["XU100 al-tut"]
        print(
            f"{n:22s} ort {dlt.mean() * 100:+.2f}%/ay  t={dlt.mean() / dlt.std() * np.sqrt(len(dlt)):+.2f}"
        )


if __name__ == "__main__":
    main()
