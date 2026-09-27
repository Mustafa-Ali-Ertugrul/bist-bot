"""Overnight (close -> next morning) paper rules O1-O3.

scripts/research/OVERNIGHT_PREREGISTRATION.md: buy at the closing auction of
day t, sell at the opening auction (or 10:30) of the next session. Universe:
point-in-time BIST 100 members, 50 most liquid by 60-day median traded value.
The rule definitions are pre-registered and intentionally not configurable.
"""

from __future__ import annotations

import pandas as pd

LIQUID_N = 50
TOP_N = 10
LIQUIDITY_WINDOW = 60
LIQUIDITY_MIN_OBS = 40
COST_PER_SIDE = 0.0005  # Midas: zero commission; auction slippage assumption
RULES = ("O1", "O2", "O3")


def liquid_universe(
    daily: dict[str, pd.DataFrame], members: list[str], as_of: pd.Timestamp
) -> list[str]:
    """Members ranked by 60-day median traded value (close x volume) up to ``as_of``."""
    traded = {}
    for ticker in dict.fromkeys(members):
        df = daily.get(ticker)
        if df is None or df.empty:
            continue
        window = df.loc[:as_of].tail(LIQUIDITY_WINDOW)
        value = (window["close"] * window["volume"]).dropna()
        if len(value) >= LIQUIDITY_MIN_OBS:
            traded[ticker] = float(value.median())
    return list(pd.Series(traded, dtype=float).nlargest(LIQUID_N).index)


def pick(today: pd.DataFrame) -> dict[str, list[str]]:
    """Rule picks from one row per ticker with today's open/high/low/close."""
    bars = today.dropna(subset=["open", "high", "low", "close"])
    bars = bars[bars["open"] > 0]
    intraday = bars["close"] / bars["open"] - 1
    span = bars["high"] - bars["low"]
    location = ((bars["close"] - bars["low"]) / span)[span > 0]
    return {
        "O1": list(bars.index),
        "O2": list(intraday.nsmallest(TOP_N).index),
        "O3": list(location.nlargest(TOP_N).index),
    }


def basket_return(entry: dict[str, float], exit_prices: dict[str, float]) -> tuple[float, int]:
    """Equal-weight gross return of the names priced on both legs, and their count."""
    rets = [
        exit_prices[t] / entry[t] - 1
        for t in entry
        if t in exit_prices and entry[t] > 0 and exit_prices[t] > 0
    ]
    return (sum(rets) / len(rets), len(rets)) if rets else (0.0, 0)


__all__ = [
    "COST_PER_SIDE",
    "LIQUID_N",
    "RULES",
    "TOP_N",
    "basket_return",
    "liquid_universe",
    "pick",
]
