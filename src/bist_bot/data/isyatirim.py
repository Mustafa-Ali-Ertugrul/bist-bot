"""Minimal İş Yatırım client: daily market data and quarterly statements.

Public endpoints used by scripts/research (HisseTekil, MaliTablo). MaliTablo
rejects requests with fewer than four periods and returns nothing if any
requested period is unpublished, so callers pass published quarters only.
"""

from __future__ import annotations

import io
import re
import time
from datetime import date

import pandas as pd
import requests

BASE = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx"
UNIVERSE_URL = (
    "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Temel-Degerler-Ve-Oranlar.aspx"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}
STATEMENT_ITEMS = ("2O", "3Z", "3C")
DAILY_COLUMNS = ("adj_close", "mcap", "volume_tl", "close_raw", "high", "low", "index_value")
CODE_RE = re.compile(r"[A-Z0-9]{2,6}")

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
    """Columns: adj_close, mcap (TL), volume_tl, close_raw, high, low; index: trading dates.

    ``adj_close`` (HGDG_KAPANIS) is the split/bonus-adjusted close and is what
    signal research uses. ``close_raw`` (HG_KAPANIS) is the unadjusted close:
    the pair differs on ex-bonus days, which is exactly the adjustment evidence
    we store instead of skipping the symbol.
    """
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
        return pd.DataFrame(columns=list(DAILY_COLUMNS))
    df = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "adj_close": pd.to_numeric(df["HGDG_KAPANIS"], errors="coerce"),
            "mcap": pd.to_numeric(df["PD"], errors="coerce"),
            "volume_tl": pd.to_numeric(df["HGDG_HACIM"], errors="coerce"),
            "close_raw": pd.to_numeric(df.get("HG_KAPANIS"), errors="coerce"),
            "high": pd.to_numeric(df.get("HGDG_MAX"), errors="coerce"),
            "low": pd.to_numeric(df.get("HGDG_MIN"), errors="coerce"),
            "index_value": pd.to_numeric(df.get("END_DEGER"), errors="coerce"),
        }
    )
    out.index = pd.to_datetime(df["HGDG_TARIH"], format="%d-%m-%Y")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[out["adj_close"].notna()]


def _flat_column(name: object) -> str:
    if isinstance(name, tuple):
        parts = [str(part) for part in name if str(part) and not str(part).startswith("Unnamed")]
        return " / ".join(parts)
    return str(name).strip()


def fetch_universe(session: requests.Session, timeout: int = 60) -> list[dict[str, str]]:
    """Listed BIST pay codes with name and sector, scraped from the public table.

    The vendor exposes no documented symbol-list endpoint, so the universe is
    read from the "Temel Değerler" table (Kod / Hisse Adı / Sektör). Rows whose
    code is not a plain ticker are ignored. Returns an empty list on failure so
    callers keep the stored universe instead of wiping it.
    """
    try:
        response = session.get(UNIVERSE_URL, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
    except (requests.RequestException, ValueError):
        return []

    chosen: pd.DataFrame | None = None
    for table in tables:
        columns = [_flat_column(column) for column in table.columns]
        if "Kod" in columns and "Hisse Adı" in columns:
            table = table.copy()
            table.columns = columns
            chosen = table
            if "Sektör" in columns:
                break
    if chosen is None:
        return []

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for _, row in chosen.iterrows():
        code = str(row.get("Kod", "") or "").strip().upper()
        if not CODE_RE.fullmatch(code) or code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "name": str(row.get("Hisse Adı", "") or "").strip(),
                "sector": str(row.get("Sektör", "") or "").strip(),
            }
        )
    return out


def fetch_index_daily(
    session: requests.Session,
    start: date,
    end: date,
    *,
    proxy_ticker: str = "THYAO",
) -> pd.DataFrame:
    """XU100 closing values from the index column of a liquid symbol's rows.

    The vendor repeats the index value on every stock row (``END_ENDEKS_KODU``
    "01" = XU100). Using one liquid symbol is cheaper than a separate endpoint.
    Returns a one-column frame indexed by date; empty on failure.
    """
    rows = _get(
        "HisseTekil",
        {
            "hisse": proxy_ticker,
            "startdate": start.strftime("%d-%m-%Y"),
            "enddate": end.strftime("%d-%m-%Y"),
        },
        session,
    )
    if not rows:
        return pd.DataFrame(columns=["value"])
    df = pd.DataFrame(rows)
    values = pd.to_numeric(df["END_DEGER"], errors="coerce")
    out = pd.DataFrame({"value": values})
    out.index = pd.to_datetime(df["HGDG_TARIH"], format="%d-%m-%Y")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[out["value"].notna()]


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
    "DAILY_COLUMNS",
    "fetch_daily",
    "fetch_index_daily",
    "fetch_statements",
    "fetch_universe",
    "published_quarters",
    "statement_available_from",
]
