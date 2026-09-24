"""Same pre-registered rules as portfolio_research.py, but the universe at each
rebalance is the reconstructed point-in-time BIST100 membership."""

import json
from pathlib import Path

import pandas as pd
import portfolio_research as pr

START = "2016-04-01"
PIT_FILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bist_bot"
    / "data"
    / "universe"
    / "bist100_pit_quarterly.json"
)

clean, raw, vol = pr.load()
idx = clean.index
cash_ret = pr.cash_daily(idx)
cash_eq = (1 + cash_ret).cumprod()
xu = clean["XU100.IS"]
sma200 = xu.rolling(200, min_periods=200).mean()

members_q = json.loads(PIT_FILE.read_text(encoding="utf-8"))["quarters"]
qstarts = sorted(members_q)


def members_at(date):
    q = max(s for s in qstarts if pd.Timestamp(s) <= date)
    return members_q[q]


stocks = [c for c in clean.columns if not c.startswith("XU")]
px = clean[stocks]
tv = (raw[stocks] * vol[stocks]).rolling(60, min_periods=40).median()

me = [d for d in pr.month_ends(idx) if d >= pd.Timestamp(START)]
pos = {d: i for i, d in enumerate(idx)}
rebals = [d for d in me if pos[d] + 1 < len(idx)]
execs = [idx[pos[d] + 1] for d in rebals]

coverage = []


def eligible(date, liq_n):
    mem = [t for t in members_at(date) if t in px.columns]
    hist = px.loc[:date, mem].tail(260).notna().sum()
    ok = list(hist[hist >= 250].index)
    coverage.append((len(members_at(date)), len(mem), len(ok)))
    s = tv.loc[date, ok].dropna()
    return list(s.nlargest(liq_n).index) if liq_n else list(s.index)


def t2_on(date):
    d0 = idx[pos[date] - 252]
    return bool(xu.loc[date] / xu.loc[d0] - 1 > cash_eq.loc[date] / cash_eq.loc[d0] - 1)


def mom(long_d, top_n=10, liq_n=50, filt=None):
    def w(date):
        if filt is not None and not filt(date):
            return pd.Series(dtype=float)
        u = eligible(date, liq_n)
        a, b = idx[pos[date] - long_d], idx[pos[date] - 21]
        sc = (px.loc[b, u] / px.loc[a, u] - 1).dropna().nlargest(top_n)
        return pd.Series(1 / len(sc), index=sc.index) if len(sc) else pd.Series(dtype=float)

    return w


def ew(liq_n=50):
    def w(date):
        u = eligible(date, liq_n)
        return pd.Series(1 / len(u), index=u) if u else pd.Series(dtype=float)

    return w


ix = clean[["XU100.IS"]]
C = pr.COST_STOCK
strategies = {
    "B1 XU100 al-tut": (lambda d: pd.Series({"XU100.IS": 1.0}), ix, pr.COST_INDEX),
    "C  nakit (PPF)": (lambda d: pd.Series(dtype=float), ix, 0.0),
    "T2 XU100 12ay>nakit": (
        lambda d: pd.Series({"XU100.IS": 1.0}) if t2_on(d) else pd.Series(dtype=float),
        ix,
        pr.COST_INDEX,
    ),
    "B2 PIT likit50 esit": (ew(50), px, C),
    "B2b PIT tum uyeler esit": (ew(0), px, C),
    "M1 PIT mom12-1 top10": (mom(252), px, C),
    "M2 PIT M1+T2": (mom(252, filt=t2_on), px, C),
    "M3 PIT mom6-1 top10": (mom(126), px, C),
    "M1 PIT top5": (mom(252, top_n=5), px, C),
    "M1 PIT top20": (mom(252, top_n=20), px, C),
    "M1 PIT tum uyeler": (mom(252, liq_n=0), px, C),
    "M1 PIT maliyet .60": (mom(252), px, 0.006),
}
curves = {n: pr.run(fn, p, cash_ret, c, rebals, execs) for n, (fn, p, c) in strategies.items()}
pd.DataFrame(curves).to_csv(f"{pr.OUT}/pit_equity.csv")

cov = pd.DataFrame(coverage, columns=["uye", "fiyat_var", "12ay_gecmis"])
m = cov.mean()
print(
    f"Kapsam (ort.): uye={m.iloc[0]:.1f} fiyat_verisi_olan={m.iloc[1]:.1f} 12ay_gecmisi_olan={m.iloc[2]:.1f}"
)

pd.set_option("display.width", 250)
for label, a, b in [
    ("2016-2026 (PIT)", None, None),
    ("2016-2019", None, "2019-12-31"),
    ("2020-2022", "2020-01-01", "2022-12-31"),
    ("2023-2026", "2023-01-01", None),
]:
    rows = {}
    for n, eq in curves.items():
        e = eq.loc[a:b]
        rows[n] = pr.stats(e / e.iloc[0], cash_eq)
    print(f"\n=== {label} ===")
    print(pd.DataFrame(rows).T.to_string())

print("\n=== Musteri gozu: 12 aylik kayan (PIT, tum donem) ===")
rows = {}
x12 = curves["B1 XU100 al-tut"].pct_change(12)
for n, eq in curves.items():
    r12 = eq.pct_change(12).dropna()
    c12 = cash_eq.reindex(eq.index).pct_change(12).dropna()
    rows[n] = {
        "12ay_zarar%": round((r12 < 0).mean() * 100),
        "nakiti_yenme%": round((r12 > c12).mean() * 100),
        "XU100u_yenme%": round((r12 > x12.dropna()).mean() * 100),
        "medyan%": round(r12.median() * 100, 1),
        "en_kotu%": round(r12.min() * 100, 1),
    }
print(pd.DataFrame(rows).T.to_string())
