"""Monthly portfolio rule "M2" (research: scripts/research, 2026-09-24).

Regime (T2): hold equities only while XU100's trailing 12-month return beats
the trailing 12-month money-market return; otherwise the whole portfolio sits
in a money-market fund.
Selection: among point-in-time BIST 100 members with >=250 of the last 260
bars, take the 50 most liquid (60-day median traded value), rank by 12-1
month momentum (close 21 bars ago / close 252 bars ago - 1) and hold the top
10 equally weighted.

The parameters are the pre-registered research values and intentionally not
configurable: tuning them live would invalidate the out-of-sample evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

LOOKBACK_BARS = 252
SKIP_BARS = 21
TOP_N = 10
LIQUID_N = 50
HISTORY_WINDOW = 260
MIN_HISTORY = 250
# BIST daily price limits make |r| > 25% a data artifact (unadjusted split).
ARTIFACT_RETURN = 0.25

PIT_FILE = Path(__file__).resolve().parents[1] / "data" / "universe" / "bist100_pit_quarterly.json"


@dataclass(frozen=True)
class MonthlyPortfolioDecision:
    as_of: date
    regime_on: bool
    index_12m_return: float | None
    cash_12m_return: float
    weights: dict[str, float] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)


def pit_members(as_of: date, pit_file: Path = PIT_FILE) -> list[str]:
    """BIST 100 members for the quarter containing ``as_of``."""
    quarters: dict[str, list[str]] = json.loads(pit_file.read_text(encoding="utf-8"))["quarters"]
    starts = [s for s in sorted(quarters) if date.fromisoformat(s) <= as_of]
    if not starts:
        raise ValueError(f"no BIST 100 membership on or before {as_of}")
    return list(quarters[starts[-1]])


def clean_prices(close: pd.DataFrame) -> pd.DataFrame:
    """Zero artifact returns and rebuild a continuous price path."""
    ret = close.pct_change(fill_method=None)
    ret = ret.mask(ret.abs() > ARTIFACT_RETURN, 0.0)
    clean = (1 + ret.fillna(0)).cumprod().where(close.notna())
    return clean.ffill(limit=5)


def decide(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    index_close: pd.Series,
    members: list[str],
    cash_12m_return: float,
    as_of: date | None = None,
) -> MonthlyPortfolioDecision:
    """Compute the M2 target portfolio at the close of ``as_of``.

    ``close``/``volume``: daily frames, one column per ticker. ``index_close``:
    XU100 closes; its dates are the trading calendar. ``cash_12m_return`` is a
    fraction (0.32 = 32%).
    """
    cols = [m for m in dict.fromkeys(members) if m in close.columns]
    # Calendar = union of index and member dates (research parity: Yahoo's XU100
    # series skips some sessions the stock series carry).
    calendar = index_close.dropna().index.union(close[cols].dropna(how="all").index)
    index_close = clean_prices(index_close.reindex(calendar).to_frame()).iloc[:, 0]
    if as_of is not None:
        calendar = calendar[calendar <= pd.Timestamp(as_of)]
    if len(calendar) == 0:
        raise ValueError("no index history")
    t = calendar[-1]
    pos = len(calendar) - 1
    decided_on = t.date()

    index_ret = None
    if pos >= LOOKBACK_BARS:
        index_ret = float(index_close.loc[t] / index_close.loc[calendar[pos - LOOKBACK_BARS]] - 1)
    regime_on = index_ret is not None and index_ret > cash_12m_return
    if not regime_on:
        return MonthlyPortfolioDecision(decided_on, False, index_ret, cash_12m_return)

    raw = close[cols].reindex(calendar)
    px = clean_prices(raw)
    hist = px.tail(HISTORY_WINDOW).notna().sum()
    eligible = list(hist[hist >= MIN_HISTORY].index)
    traded = (raw * volume.reindex(calendar)[cols]).rolling(60, min_periods=40).median()
    liquid = traded.loc[t, eligible].dropna().nlargest(LIQUID_N).index
    a, b = calendar[pos - LOOKBACK_BARS], calendar[pos - SKIP_BARS]
    score = (px.loc[b, liquid] / px.loc[a, liquid] - 1).dropna().nlargest(TOP_N)
    weights = {str(k): 1.0 / len(score) for k in score.index} if len(score) else {}
    return MonthlyPortfolioDecision(
        decided_on,
        True,
        index_ret,
        cash_12m_return,
        weights,
        {str(k): float(v) for k, v in score.items()},
    )


__all__ = ["PIT_FILE", "MonthlyPortfolioDecision", "clean_prices", "decide", "pit_members"]
