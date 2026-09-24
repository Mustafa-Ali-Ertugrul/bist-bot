"""Monthly paper-portfolio ledger shared by the M2 service and the strategy league.

Returns are recomputed from the *current* price history between the previous
and the current rebalance date. Storing entry prices instead would break on
BIST bonus issues (bedelsiz): the data provider re-bases past prices, so an
old stored price against a freshly adjusted one shows a fake -50%.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from bist_bot.strategy.monthly_portfolio import clean_prices

COST_PER_SIDE = 0.0035  # research cost model: commission + BSMV + spread/slippage


def _price_on(px: pd.DataFrame, when: date) -> pd.Series:
    upto = px.loc[: pd.Timestamp(when)]
    return upto.iloc[-1] if len(upto) else pd.Series(dtype=float)


def mark_to_market(
    state: dict[str, Any],
    weights: dict[str, float],
    panel: pd.DataFrame,
    index_ticker: str,
    as_of: date,
    cash_pct: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Value the previous holdings up to ``as_of`` and switch to ``weights``.

    ``panel``: daily closes (dates x tickers) incl. ``index_ticker``. Returns
    the new state and a history row. A holding without a price on either date
    is carried flat (growth 1.0).
    """
    px = clean_prices(panel.sort_index())
    nav = float(state.get("nav", 1.0))
    index_nav = float(state.get("index_nav", 1.0))
    cash_nav = float(state.get("cash_nav", 1.0))
    drifted: dict[str, float] = {}
    period_growth = 1.0
    if state:
        start = date.fromisoformat(state["last_rebalance"])
        p0, p1 = _price_on(px, start), _price_on(px, as_of)

        def growth(ticker: str) -> float:
            a, b = p0.get(ticker), p1.get(ticker)
            return float(b) / float(a) if pd.notna(a) and pd.notna(b) and a > 0 else 1.0

        cash_growth = (1 + float(state["cash_rate_pct"]) / 100.0) ** ((as_of - start).days / 365.0)
        holdings: dict[str, float] = state.get("holdings", {})
        g = {t: growth(t) for t in holdings}
        invested = sum(holdings.values())
        period_growth = sum(w * g[t] for t, w in holdings.items()) + (1 - invested) * cash_growth
        drifted = {t: w * g[t] / period_growth for t, w in holdings.items()}
        index_nav *= growth(index_ticker)
        cash_nav *= cash_growth
    tickers = set(drifted) | set(weights)
    turnover = sum(abs(weights.get(t, 0.0) - drifted.get(t, 0.0)) for t in tickers)
    nav *= period_growth * (1 - turnover * COST_PER_SIDE)
    new_state = {
        "last_rebalance": as_of.isoformat(),
        "nav": nav,
        "index_nav": index_nav,
        "cash_nav": cash_nav,
        "cash_rate_pct": cash_pct,
        "holdings": dict(weights),
    }
    row = {
        "date": as_of.isoformat(),
        "holdings": " ".join(weights),
        "period_return": period_growth - 1,
        "turnover": turnover,
        "nav": nav,
        "index_nav": index_nav,
        "cash_nav": cash_nav,
    }
    return new_state, row


__all__ = ["COST_PER_SIDE", "mark_to_market"]
