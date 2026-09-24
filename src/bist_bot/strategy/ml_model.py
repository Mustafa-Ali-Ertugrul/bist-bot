"""Conditional multi-factor model (scripts/research/ML_PREREGISTRATION.md).

Stock conditions are ranked cross-sectionally each month (robust to TL
inflation); market conditions are shared by all stocks so the trees can learn
which stock conditions matter in which market regime. Parameters are fixed by
the pre-registration — do not tune.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

STOCK_FEATURES = [
    "ret_1m",
    "mom_6_1",
    "mom_12_1",
    "vol_3m",
    "dist_52w_high",
    "volume_trend",
    "log_mcap",
    "book_to_market",
    "earnings_yield",
    "roe",
    "earnings_surprise",
    "sales_growth",
]
MARKET_FEATURES = ["xu_12m_ex_cash", "cash_12m", "xu_1m", "xu_vol_3m", "usd_3m"]
FEATURES = STOCK_FEATURES + MARKET_FEATURES
MODEL_PARAMS = {
    "max_depth": 3,
    "n_estimators": 300,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "random_state": 0,
    "n_jobs": 4,
}


@dataclass(frozen=True)
class Panel:
    """Aligned daily inputs on one trading calendar ``idx`` (cleaned prices)."""

    px: pd.DataFrame
    mcap: pd.DataFrame
    volume_tl: pd.DataFrame
    xu: pd.Series
    usd: pd.Series
    fundamentals: dict[str, pd.DataFrame]


def features_at(panel: Panel, i: int, universe: list[str], cash_12m: float) -> pd.DataFrame:
    """Feature rows (index = tickers) at calendar position ``i``."""
    px, idx = panel.px, panel.px.index
    t = idx[i]
    cur = px.iloc[i][universe]
    window = px.iloc[max(0, i - 251) : i + 1][universe]
    daily_ret = px.iloc[max(0, i - 63) : i + 1][universe].pct_change(fill_method=None)
    vol = panel.volume_tl.iloc[max(0, i - 125) : i + 1][universe]
    f = pd.DataFrame(index=universe, dtype=float)
    f["ret_1m"] = cur / px.iloc[i - 21][universe] - 1
    f["mom_6_1"] = px.iloc[i - 21][universe] / px.iloc[i - 126][universe] - 1
    f["mom_12_1"] = px.iloc[i - 21][universe] / px.iloc[i - 252][universe] - 1
    f["vol_3m"] = daily_ret.std()
    f["dist_52w_high"] = cur / window.max() - 1
    f["volume_trend"] = vol.tail(21).median() / vol.median()
    f["log_mcap"] = np.log(panel.mcap.iloc[i][universe].where(lambda s: s > 0))
    for tk in universe:
        fund = panel.fundamentals.get(tk)
        if fund is None or fund.empty:
            continue
        fund = fund.loc[:t]
        if fund.empty:
            continue
        last = fund.iloc[-1]
        mc = panel.mcap.iloc[i].get(tk)
        if not mc or not np.isfinite(mc):
            continue
        eq, ttm = last["equity"], last["ttm"]
        f.loc[tk, "book_to_market"] = eq / mc if eq > 0 else np.nan
        f.loc[tk, "earnings_yield"] = ttm / mc
        f.loc[tk, "roe"] = ttm / eq if eq > 0 else np.nan
        f.loc[tk, "earnings_surprise"] = (last["ni_q"] - last["ni_q_ly"]) / mc
        if last["sales_q"] > 0 and last["sales_q_ly"] > 0:
            f.loc[tk, "sales_growth"] = last["sales_q"] / last["sales_q_ly"] - 1
    f = f.replace([np.inf, -np.inf], np.nan).rank(pct=True)
    xu = panel.xu
    xu_ret = xu.iloc[max(0, i - 63) : i + 1].pct_change(fill_method=None)
    f["xu_12m_ex_cash"] = xu.iloc[i] / xu.iloc[i - 252] - 1 - cash_12m
    f["cash_12m"] = cash_12m
    f["xu_1m"] = xu.iloc[i] / xu.iloc[i - 21] - 1
    f["xu_vol_3m"] = xu_ret.std()
    f["usd_3m"] = panel.usd.iloc[i] / panel.usd.iloc[i - 63] - 1
    return f[FEATURES]


def fit(x: pd.DataFrame, y: pd.Series) -> XGBRegressor:
    known = y.notna()  # e.g. delisted before the next rebalance
    model = XGBRegressor(**MODEL_PARAMS)
    model.fit(x.loc[known, FEATURES], y[known])
    return model


def top_n(model: XGBRegressor, x: pd.DataFrame, n: int = 10) -> dict[str, float]:
    pred = pd.Series(model.predict(x[FEATURES]), index=x.index).nlargest(n)
    return {str(t): 1.0 / len(pred) for t in pred.index} if len(pred) else {}


__all__ = ["FEATURES", "MODEL_PARAMS", "Panel", "features_at", "fit", "top_n"]
