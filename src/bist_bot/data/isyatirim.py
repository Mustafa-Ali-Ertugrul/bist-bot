"""Minimal İş Yatırım client: daily market data and quarterly statements.

Public endpoints used by scripts/research (HisseTekil, MaliTablo). MaliTablo
rejects requests with fewer than four periods and returns nothing if any
requested period is unpublished, so callers pass published quarters only.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import requests

BASE = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0"}
STATEMENT_ITEMS = ("2O", "3Z", "3C")
# Quarter-end month -> first date its statement may be used (month, day, year offset).
STATEMENT_LAG = {3: (6, 15, 0), 6: (9, 15, 0), 9: (12, 15, 0), 12: (4, 15, 1)}


def _get(endpoint: str, params: dict[str, object], session: requests.Session) -> list[dict]:
    for attempt in range(3):
        try:
            r = session.get(f"{BASE}/{endpoint}", params=params, headers=HEADERS, timeout=30)
            if r.ok:
                return r.json().get("value") or []
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (attempt + 1))
    return []


def statement_available_from(year: int, month: int) -> date:
    m, d, off = STATEMENT_LAG[month]
    return date(year + off, m, d)


def published_quarters(as_of: date, count: int) -> list[tuple[int, int]]:
    """The ``count`` most recent quarters whose statements are usable at ``as_of``."""
    out: list[tuple[int, int]] = []
    y, m = as_of.year, 12
    while len(out) < count:
        if statement_available_from(y, m) <= as_of:
            out.append((y, m))
        m -= 3
        if m == 0:
            y, m = y - 1, 12
    return out


def fetch_daily(code: str, start: date, end: date, session: requests.Session) -> pd.DataFrame:
    """Columns: adj_close, mcap (TL), volume_tl; index: trading dates."""
    rows = _get(
        "HisseTekil",
        {
            "hisse": code,
            "startdate": start.strftime("%d-%m-%Y"),
            "enddate": end.strftime("%d-%m-%Y"),
        },
        session,
    )
    if not rows:
        return pd.DataFrame(columns=["adj_close", "mcap", "volume_tl"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "adj_close": pd.to_numeric(df["HGDG_KAPANIS"], errors="coerce"),
            "mcap": pd.to_numeric(df["PD"], errors="coerce"),
            "volume_tl": pd.to_numeric(df["HGDG_HACIM"], errors="coerce"),
        }
    )
    out.index = pd.to_datetime(df["HGDG_TARIH"], format="%d-%m-%Y")
    return out[~out.index.duplicated(keep="last")].sort_index()


def fetch_statements(
    code: str, quarters: list[tuple[int, int]], session: requests.Session
) -> dict[str, dict[str, float]]:
    """{"YYYY/MM": {"2O": equity, "3Z": net profit YTD, "3C": sales YTD}}."""
    chunks = [quarters[i : i + 4] for i in range(0, len(quarters), 4)]
    chunks[-1] = (chunks[-1] * 4)[:4]
    out: dict[str, dict[str, float]] = {}
    for group in ("XI_29", "UFRS"):
        for chunk in chunks:
            params: dict[str, object] = {
                "companyCode": code,
                "exchange": "TRY",
                "financialGroup": group,
            }
            for j, (y, m) in enumerate(chunk, start=1):
                params[f"year{j}"], params[f"period{j}"] = y, m
            for row in _get("MaliTablo", params, session):
                if row.get("itemCode") not in STATEMENT_ITEMS:
                    continue
                for j, (y, m) in enumerate(chunk, start=1):
                    val = row.get(f"value{j}")
                    if val not in (None, "", "0"):
                        out.setdefault(f"{y}/{m:02d}", {})[row["itemCode"]] = float(val)
        if out:
            break
    return out


__all__ = [
    "fetch_daily",
    "fetch_statements",
    "published_quarters",
    "statement_available_from",
]
