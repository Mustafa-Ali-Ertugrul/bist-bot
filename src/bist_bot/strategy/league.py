"""Live paper strategy league (scripts/research/LEAGUE_PREREGISTRATION.md).

18 pre-registered monthly rules in three groups of six. Definitions match
scripts/research/factor_backtest.py; do not change a rule once the league has
started — add a new, separately pre-registered strategy instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from bist_bot.data.isyatirim import statement_available_from
from bist_bot.strategy.monthly_portfolio import (
    HISTORY_WINDOW,
    LIQUID_N,
    LOOKBACK_BARS,
    MIN_HISTORY,
    SKIP_BARS,
    clean_prices,
)

INDEX_TICKER = "XU100.IS"


@dataclass(frozen=True)
class Spec:
    name: str
    family: str  # MOM, INDEX, E1, E2, V1, C1, Q1, C2, EW
    top_n: int = 10
    regime: bool = False


SPECS: tuple[Spec, ...] = (
    Spec("A1 M2", "MOM", regime=True),
    Spec("A2 T2", "INDEX", regime=True),
    Spec("A3 E1", "E1"),
    Spec("A4 E2", "E2"),
    Spec("A5 V1", "V1"),
    Spec("A6 C1", "C1"),
    Spec("B1 R+E1", "E1", regime=True),
    Spec("B2 R+E2", "E2", regime=True),
    Spec("B3 R+V1", "V1", regime=True),
    Spec("B4 R+C1", "C1", regime=True),
    Spec("B5 R+Q1", "Q1", regime=True),
    Spec("B6 R+C2", "C2", regime=True),
    Spec("C1 MOM5", "MOM", top_n=5),
    Spec("C2 MOM20", "MOM", top_n=20),
    Spec("C3 E2-5", "E2", top_n=5),
    Spec("C4 E2-20", "E2", top_n=20),
    Spec("C5 V1-20", "V1", top_n=20),
    Spec("C6 EW50", "EW"),
)


def build_fundamentals(raw: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Statement rows indexed by first-usable date: equity, TTM profit, quarter profit/sales."""
    if not raw:
        return pd.DataFrame()
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

    def ytd(y: int, m: int, col: str = "ytd") -> float:
        return float(f[col].get((y, m), np.nan))

    def quarter(y: int, m: int, col: str) -> float:
        return ytd(y, m, col) - (ytd(y, m - 3, col) if m > 3 else 0.0)

    rows = []
    for y, m in f.index:
        ttm = ytd(y, 12) if m == 12 else ytd(y, m) + ytd(y - 1, 12) - ytd(y - 1, m)
        rows.append(
            {
                "avail": pd.Timestamp(statement_available_from(y, m)),
                "equity": f.loc[(y, m), "eq"],
                "ttm": ttm,
                "ni_q": quarter(y, m, "ytd"),
                "ni_q_ly": quarter(y - 1, m, "ytd"),
                "sales_q": quarter(y, m, "sales_ytd"),
                "sales_q_ly": quarter(y - 1, m, "sales_ytd"),
            }
        )
    return pd.DataFrame(rows).set_index("avail").sort_index()


@dataclass(frozen=True)
class LeagueInputs:
    adj_close: pd.DataFrame  # dates x tickers (.IS)
    mcap: pd.DataFrame
    volume_tl: pd.DataFrame
    fundamentals: dict[str, pd.DataFrame]  # ticker -> build_fundamentals()
    index_close: pd.Series
    members: list[str]
    cash_12m_return: float


def _top(score: pd.Series, n: int) -> dict[str, float]:
    s = score.replace([np.inf, -np.inf], np.nan).dropna().nlargest(n)
    return {str(t): 1.0 / len(s) for t in s.index} if len(s) else {}


def decide_league(inputs: LeagueInputs, as_of: date) -> tuple[bool, dict[str, dict[str, float]]]:
    """Return (regime_on, {strategy name: weights}) at the close of ``as_of``."""
    idx = inputs.adj_close.index.union(inputs.index_close.dropna().index)
    idx = idx[idx <= pd.Timestamp(as_of)]
    t, i = idx[-1], len(idx) - 1
    px = clean_prices(inputs.adj_close.reindex(idx))
    mcap = inputs.mcap.reindex(idx).ffill(limit=5)
    tv = inputs.volume_tl.reindex(idx).rolling(60, min_periods=40).median()
    xu = clean_prices(inputs.index_close.reindex(idx).to_frame()).iloc[:, 0]

    regime_on = False
    if i >= LOOKBACK_BARS:
        regime_on = bool(xu.iloc[i] / xu.iloc[i - LOOKBACK_BARS] - 1 > inputs.cash_12m_return)

    mem = [m for m in dict.fromkeys(inputs.members) if m in px.columns]
    hist = px[mem].tail(HISTORY_WINDOW).notna().sum()
    ok = hist[hist >= MIN_HISTORY].index
    universe = list(tv.loc[t, ok].dropna().nlargest(LIQUID_N).index)
    momentum = px.loc[idx[i - SKIP_BARS], universe] / px.loc[idx[i - LOOKBACK_BARS], universe] - 1

    rows = {}
    for tk in universe:
        f = inputs.fundamentals.get(tk)
        if f is None or f.empty:
            continue
        f = f.loc[:t]
        if not f.empty:
            rows[tk] = {**f.iloc[-1].to_dict(), "mcap": mcap.loc[t, tk]}
    fund = pd.DataFrame(rows).T.astype(float) if rows else pd.DataFrame()

    scores: dict[str, pd.Series] = {"MOM": momentum}
    if not fund.empty:
        eq, ttm, mc = fund["equity"], fund["ttm"], fund["mcap"]
        bm = (eq / mc).where(eq > 0)
        ep = (ttm / mc).where(ttm > 0)
        roe = (ttm / eq).where(eq > 0)
        ok_sales = (fund["sales_q"] > 0) & (fund["sales_q_ly"] > 0)
        mom_f = momentum.reindex(fund.index)
        scores.update(
            {
                "V1": bm,
                "Q1": roe,
                "E1": (fund["ni_q"] - fund["ni_q_ly"]) / mc,
                "E2": (fund["sales_q"] / fund["sales_q_ly"] - 1).where(ok_sales),
                "C1": (bm.rank(pct=True) + mom_f.rank(pct=True)) / 2,
                "C2": (ep.rank(pct=True) + roe.rank(pct=True)) / 2,
            }
        )

    out: dict[str, dict[str, float]] = {}
    for spec in SPECS:
        if spec.regime and not regime_on:
            out[spec.name] = {}
        elif spec.family == "INDEX":
            out[spec.name] = {INDEX_TICKER: 1.0}
        elif spec.family == "EW":
            out[spec.name] = {tk: 1.0 / len(universe) for tk in universe} if universe else {}
        elif spec.family in scores:
            out[spec.name] = _top(scores[spec.family], spec.top_n)
        else:
            out[spec.name] = {}
    return regime_on, out


__all__ = ["INDEX_TICKER", "SPECS", "LeagueInputs", "Spec", "build_fundamentals", "decide_league"]
