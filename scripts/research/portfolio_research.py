"""Pre-registered monthly portfolio strategy study on BIST (research only).

WARNING: the universe here is today's BIST100 list projected backward
(survivorship-biased). Use pit_backtest.py for the point-in-time result.

All rules/parameters are fixed up front (standard literature values); no tuning.
Signal at month-end close, execution at next trading day's close (1-day lag).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

# Price cache written by fetch_prices.py (gitignored).
OUT = os.environ.get("RESEARCH_CACHE", "tmp/research_cache")
COST_STOCK = 0.0035  # per side: commission+BSMV+spread/slippage
COST_INDEX = 0.0020  # per side, index ETF proxy
CASH_NET = 0.85  # money-market net of fees/withholding, as share of policy rate
TOP_N = 10
LIQ_N = 50
START = "2012-01-01"

# Approximate TCMB one-week repo policy rate (annual %), effective from date.
POLICY = [
    ("2010-01-01", 6.5),
    ("2011-01-01", 6.25),
    ("2011-08-01", 5.75),
    ("2012-01-01", 5.75),
    ("2012-12-01", 5.5),
    ("2013-05-01", 4.5),
    ("2014-01-29", 10.0),
    ("2014-05-22", 9.5),
    ("2014-06-24", 8.75),
    ("2014-07-17", 8.25),
    ("2015-01-20", 7.75),
    ("2015-02-24", 7.5),
    ("2017-01-01", 9.5),
    ("2017-06-01", 12.0),
    ("2018-06-07", 17.75),
    ("2018-09-13", 24.0),
    ("2019-07-25", 19.75),
    ("2019-09-12", 16.5),
    ("2019-10-24", 14.0),
    ("2019-12-12", 12.0),
    ("2020-01-16", 11.25),
    ("2020-02-19", 10.75),
    ("2020-03-17", 9.75),
    ("2020-04-22", 8.75),
    ("2020-05-21", 8.25),
    ("2020-09-24", 10.25),
    ("2020-11-19", 15.0),
    ("2020-12-24", 17.0),
    ("2021-03-18", 19.0),
    ("2021-09-23", 18.0),
    ("2021-10-21", 16.0),
    ("2021-11-18", 15.0),
    ("2021-12-16", 14.0),
    ("2022-08-18", 13.0),
    ("2022-09-22", 12.0),
    ("2022-10-20", 10.5),
    ("2022-11-24", 9.0),
    ("2023-02-23", 8.5),
    ("2023-06-22", 15.0),
    ("2023-07-20", 17.5),
    ("2023-08-24", 25.0),
    ("2023-09-21", 30.0),
    ("2023-10-26", 35.0),
    ("2023-11-23", 40.0),
    ("2023-12-21", 42.5),
    ("2024-01-25", 45.0),
    ("2024-03-21", 50.0),
    ("2024-12-26", 47.5),
    ("2025-01-23", 45.0),
    ("2025-03-06", 42.5),
    ("2025-04-17", 46.0),
    ("2025-07-24", 43.0),
    ("2025-09-11", 40.5),
    ("2025-10-23", 39.5),
    ("2025-12-11", 38.0),
    ("2026-01-22", 37.0),
    ("2026-04-01", 35.0),
]


def load():
    close = pd.read_parquet(f"{OUT}/close.parquet").sort_index()
    volume = pd.read_parquet(f"{OUT}/volume.parquet").reindex(close.index)
    close = close.dropna(how="all")
    volume = volume.reindex(close.index)
    # Clean: BIST daily limits (+-10%, historically +-20%) make |r|>25% a data artifact
    # (unadjusted split / bedelsiz). Zero those days and rebuild a clean price path.
    ret = close.pct_change(fill_method=None)
    ret = ret.mask(ret.abs() > 0.25, 0.0)
    clean = (1 + ret.fillna(0)).cumprod().where(close.notna())
    clean = clean.ffill(limit=5)
    return clean, close, volume


def cash_daily(index):
    s = pd.Series({pd.Timestamp(d): r for d, r in POLICY}).sort_index()
    rate = s.reindex(index.union(s.index)).ffill().reindex(index) / 100 * CASH_NET
    return (1 + rate) ** (1 / 252) - 1


def month_ends(index):
    s = pd.Series(index, index=index)
    return list(s.groupby([index.year, index.month]).max())


def run(weights_fn, px, cash_ret, cost, rebals, execs):
    """Monthly rebalanced backtest. weights_fn(signal_date) -> pd.Series weights (sum<=1)."""
    equity = [1.0]
    dates = [execs[0]]
    w_prev = pd.Series(dtype=float)
    cash_growth = (1 + cash_ret).cumprod()
    for k in range(len(execs) - 1):
        sig, ex, ex_next = rebals[k], execs[k], execs[k + 1]
        w = weights_fn(sig).fillna(0.0)
        w = w[w > 0]
        turnover = (
            (
                w.reindex(w.index.union(w_prev.index), fill_value=0)
                - w_prev.reindex(w.index.union(w_prev.index), fill_value=0)
            )
            .abs()
            .sum()
        )
        growth = (px.loc[ex_next, w.index] / px.loc[ex, w.index]).fillna(1.0)
        cash_w = max(0.0, 1.0 - w.sum())
        cg = cash_growth.loc[ex_next] / cash_growth.loc[ex]
        period = float((w * growth).sum() + cash_w * cg)
        equity.append(equity[-1] * period * (1 - turnover * cost))
        dates.append(ex_next)
        drift = w * growth
        w_prev = drift / period if period > 0 else drift
    return pd.Series(equity, index=dates)


def stats(eq, cash_eq):
    m = eq.pct_change().dropna()
    cm = cash_eq.reindex(eq.index).pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    ccagr = (cash_eq.reindex(eq.index).iloc[-1] / cash_eq.reindex(eq.index).iloc[0]) ** (
        1 / yrs
    ) - 1
    dd = (eq / eq.cummax() - 1).min()
    ex = m - cm
    sharpe = ex.mean() / ex.std() * np.sqrt(12) if ex.std() > 0 else np.nan
    return {
        "CAGR%": round(cagr * 100, 1),
        "nakit_ustu%": round((cagr - ccagr) * 100, 1),
        "maxDD%": round(dd * 100, 1),
        "Sharpe(nakit)": round(sharpe, 2),
        "pozitif_ay%": round((m > 0).mean() * 100, 0),
        "en_kotu_ay%": round(m.min() * 100, 1),
        "ay": len(m),
    }


def main():
    clean, raw, vol = load()
    idx = clean.index
    cash_ret = cash_daily(idx)
    cash_eq = (1 + cash_ret).cumprod()
    xu = clean["XU100.IS"]
    stocks = [c for c in clean.columns if not c.startswith("XU")]
    px = clean[stocks]
    tv = (raw[stocks] * vol[stocks]).rolling(60, min_periods=40).median()
    sma200 = xu.rolling(200, min_periods=200).mean()
    ret_d = px.pct_change(fill_method=None)
    vol126 = ret_d.rolling(126, min_periods=100).std()

    me = [d for d in month_ends(idx) if d >= pd.Timestamp(START)]
    pos = {d: i for i, d in enumerate(idx)}
    rebals = [d for d in me if pos[d] + 1 < len(idx)]
    execs = [idx[pos[d] + 1] for d in rebals]

    def lookback(date, days):
        i = pos[date]
        return idx[i - days] if i - days >= 0 else None

    def eligible(date):
        hist = px.loc[:date].tail(260).notna().sum()
        ok = hist[hist >= 250].index
        liq = tv.loc[date, ok].dropna().nlargest(LIQ_N)
        return list(liq.index)

    def xu_on_t1(date):
        return bool(xu.loc[date] > sma200.loc[date]) if pd.notna(sma200.loc[date]) else False

    def xu_on_t2(date):
        d0 = lookback(date, 252)
        if d0 is None:
            return False
        r_eq = xu.loc[date] / xu.loc[d0] - 1
        r_cash = cash_eq.loc[date] / cash_eq.loc[d0] - 1
        return bool(r_eq > r_cash)

    def mom(date, long_d, skip_d, filt=None):
        if filt is not None and not filt(date):
            return pd.Series(dtype=float)
        a, b = lookback(date, long_d), lookback(date, skip_d)
        if a is None:
            return pd.Series(dtype=float)
        u = eligible(date)
        score = (px.loc[b, u] / px.loc[a, u] - 1).dropna()
        top = score.nlargest(TOP_N).index
        return pd.Series(1.0 / len(top), index=top) if len(top) else pd.Series(dtype=float)

    def lowvol(date):
        u = eligible(date)
        s = vol126.loc[date, u].dropna().nsmallest(TOP_N).index
        return pd.Series(1.0 / len(s), index=s) if len(s) else pd.Series(dtype=float)

    def ew(date):
        u = eligible(date)
        return pd.Series(1.0 / len(u), index=u) if u else pd.Series(dtype=float)

    ix = clean[["XU100.IS"]]
    strategies = {
        "B1 XU100 al-tut": (lambda d: pd.Series({"XU100.IS": 1.0}), ix, COST_INDEX),
        "C  nakit (PPF)": (lambda d: pd.Series(dtype=float), ix, 0.0),
        "T1 XU100>SMA200 else nakit": (
            lambda d: pd.Series({"XU100.IS": 1.0}) if xu_on_t1(d) else pd.Series(dtype=float),
            ix,
            COST_INDEX,
        ),
        "T2 XU100 12ay>nakit else nakit": (
            lambda d: pd.Series({"XU100.IS": 1.0}) if xu_on_t2(d) else pd.Series(dtype=float),
            ix,
            COST_INDEX,
        ),
        "B2 likit50 esit agirlik": (ew, px, COST_STOCK),
        "M1 momentum 12-1 top10": (lambda d: mom(d, 252, 21), px, COST_STOCK),
        "M2 M1 + T2 filtresi": (lambda d: mom(d, 252, 21, xu_on_t2), px, COST_STOCK),
        "M3 momentum 6-1 top10": (lambda d: mom(d, 126, 21), px, COST_STOCK),
        "L1 dusuk vol top10": (lowvol, px, COST_STOCK),
    }
    curves = {}
    for name, (fn, prices, cost) in strategies.items():
        curves[name] = run(fn, prices, cash_ret, cost, rebals, execs)
    pd.DataFrame(curves).to_csv(f"{OUT}/equity_curves.csv")

    periods = [
        ("TUM 2012-2026", None, None),
        ("2012-2017", None, "2017-12-31"),
        ("2018-2022", "2018-01-01", "2022-12-31"),
        ("2023-2026", "2023-01-01", None),
    ]
    pd.set_option("display.width", 250)
    for label, a, b in periods:
        rows = {}
        for name, eq in curves.items():
            e = eq.loc[a:b]
            rows[name] = stats(e / e.iloc[0], cash_eq)
        print(f"\n=== {label} ===")
        print(pd.DataFrame(rows).T.to_string())

    # Customer view: rolling 12-month outcome
    print("\n=== Musteri gozu: 12 aylik kayan getiriler (tum donem) ===")
    rows = {}
    for name, eq in curves.items():
        r12 = eq.pct_change(12).dropna()
        c12 = cash_eq.reindex(eq.index).pct_change(12).dropna()
        x12 = curves["B1 XU100 al-tut"].pct_change(12).dropna()
        rows[name] = {
            "12ay_zarar_olasiligi%": round((r12 < 0).mean() * 100, 0),
            "12ay_nakiti_yenme%": round((r12 > c12).mean() * 100, 0),
            "12ay_XU100u_yenme%": round((r12 > x12).mean() * 100, 0),
            "12ay_medyan%": round(r12.median() * 100, 1),
            "12ay_en_kotu%": round(r12.min() * 100, 1),
        }
    print(pd.DataFrame(rows).T.to_string())


if __name__ == "__main__":
    main()
