"""Walk-forward test of the pre-registered ML model (ML_PREREGISTRATION.md).

Run from scripts/research:  python ml_backtest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import factor_backtest as fb
import portfolio_research as pr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from bist_bot.strategy import league as lg  # noqa: E402
from bist_bot.strategy import ml_model as ml  # noqa: E402
from bist_bot.strategy.monthly_portfolio import pit_members  # noqa: E402

FIRST_PREDICTION = pd.Timestamp("2019-01-01")


def main() -> None:
    adj, mcap, vol = fb.load_daily()
    raw = {
        p.name.removesuffix("_fin.json") + ".IS": json.loads(p.read_text(encoding="utf-8"))
        for p in fb.ISY.glob("*_fin.json")
    }
    fund = {k: lg.build_fundamentals(v) for k, v in raw.items() if v}
    clean, _, _ = pr.load()
    xu_raw = clean["XU100.IS"]
    usd = pd.read_parquet(Path(pr.OUT) / "usdtry.parquet")["USDTRY"]
    usd.index = pd.to_datetime(usd.index).normalize()
    idx = adj.index.union(xu_raw.dropna().index)
    ret = adj.reindex(idx).pct_change(fill_method=None)
    ret = ret.mask(ret.abs() > 0.25, 0.0)
    px = (1 + ret.fillna(0)).cumprod().where(adj.reindex(idx).notna()).ffill(limit=5)
    panel = ml.Panel(
        px=px,
        mcap=mcap.reindex(idx).ffill(limit=5),
        volume_tl=vol.reindex(idx),
        xu=xu_raw.reindex(idx).ffill(limit=5),
        usd=usd.reindex(idx.union(usd.index)).ffill().reindex(idx),
        fundamentals=fund,
    )
    tv = vol.reindex(idx).rolling(60, min_periods=40).median()
    cash_ret = pr.cash_daily(idx)
    cash_eq = (1 + cash_ret).cumprod()
    pos = {d: i for i, d in enumerate(idx)}
    rebals = [d for d in pr.month_ends(idx) if d >= pd.Timestamp("2016-04-01") and pos[d] + 1 < len(idx)]
    execs = [idx[pos[d] + 1] for d in rebals]

    months = []
    for k, d in enumerate(rebals):
        i = pos[d]
        mem = [m for m in pit_members(d.date()) if m in px.columns]
        hist = px.iloc[max(0, i - 259) : i + 1][mem].notna().sum()
        ok = hist[hist >= 250].index
        uni = list(tv.loc[d, ok].dropna().nlargest(50).index)
        c12 = float(cash_eq.iloc[i] / cash_eq.iloc[i - 252] - 1)
        x = ml.features_at(panel, i, uni, c12)
        y = None
        if k + 1 < len(execs):
            fwd = px.loc[execs[k + 1], uni] / px.loc[execs[k], uni] - 1
            y = fwd.rank(pct=True)
        regime = bool(panel.xu.iloc[i] / panel.xu.iloc[i - 252] - 1 > c12)
        months.append({"date": d, "x": x, "y": y, "fwd": fwd if y is not None else None, "regime": regime, "uni": uni})

    d1, d2, ics = {}, {}, []
    for k, m in enumerate(months):
        if m["date"] < FIRST_PREDICTION:
            continue
        train = [months[j] for j in range(k - 1) if months[j]["y"] is not None]
        xt = pd.concat([t["x"] for t in train])
        yt = pd.concat([t["y"] for t in train])
        model = ml.fit(xt, yt)
        w = ml.top_n(model, m["x"], 10)
        d1[m["date"]] = w
        d2[m["date"]] = w if m["regime"] else {}
        if m["fwd"] is not None:
            pred = pd.Series(model.predict(m["x"][ml.FEATURES]), index=m["x"].index)
            both = pd.concat([pred, m["fwd"]], axis=1).dropna()
            ics.append((m["date"], spearmanr(both.iloc[:, 0], both.iloc[:, 1]).statistic))

    ic = pd.Series(dict(ics))
    print(f"Bilgi katsayisi: ort {ic.mean():+.4f}  t={ic.mean() / ic.std() * np.sqrt(len(ic)):+.2f}  n={len(ic)}")
    for label, a, b in [("2019-2022", "2019", "2022"), ("2023-2026", "2023", "2026")]:
        s = ic.loc[a:b]
        print(f"  {label}: ort {s.mean():+.4f}  t={s.mean() / s.std() * np.sqrt(len(s)):+.2f}")

    start = [k for k, d in enumerate(rebals) if d >= FIRST_PREDICTION][0]
    rb, ex = rebals[start:], execs[start:]
    px_all = px.copy()
    px_all["XU100.IS"] = panel.xu
    uni_by_date = {m["date"]: m["uni"] for m in months}
    strategies = {
        "XU100 al-tut": (lambda d: pd.Series({"XU100.IS": 1.0}), pr.COST_INDEX),
        "Para piyasasi": (lambda d: pd.Series(dtype=float), 0.0),
        "Likit50 esit": (lambda d: pd.Series(1 / len(uni_by_date[d]), index=uni_by_date[d]), pr.COST_STOCK),
        "D1 ML10": (lambda d: pd.Series(d1[d], dtype=float), pr.COST_STOCK),
        "D2 R+ML10": (lambda d: pd.Series(d2[d], dtype=float), pr.COST_STOCK),
    }
    curves = {n: pr.run(fn, px_all, cash_ret, c, rb, ex) for n, (fn, c) in strategies.items()}
    pd.set_option("display.width", 250)
    for label, a, b in [("2019-2022", None, "2022-12-31"), ("2023-2026", "2023-01-01", None), ("2019-2026", None, None)]:
        rows = {}
        for n, eq in curves.items():
            e = eq.loc[a:b]
            rows[n] = pr.stats(e / e.iloc[0], cash_eq)
        print(f"\n=== {label} ===")
        print(pd.DataFrame(rows).T.to_string())
    pd.DataFrame(curves).to_csv(Path(pr.OUT) / "ml_equity.csv")


if __name__ == "__main__":
    main()
