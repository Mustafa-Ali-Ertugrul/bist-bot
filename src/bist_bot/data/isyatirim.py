"""Minimal İş Yatırım client: daily market data and quarterly statements.

Public endpoints used by scripts/research (HisseTekil, MaliTablo). MaliTablo
rejects requests with fewer than four periods and returns nothing if any
requested period is unpublished, so callers pass published quarters only.
"""

from __future__ import annotations

import io
import re
import time
from datetime import date, datetime

import lxml.html as lxml_html
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


def _tr_number(raw: object) -> float | None:
    """Parse a Turkish-formatted number (``1.234,56``) from a raw HTML cell."""
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "").replace("\u00a0", "")
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(".", "") if text.count(".") > 1 else text
    try:
        return float(text)
    except ValueError:
        return None


def _tr_date(raw: object) -> date | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


ACTION_FIELD_NAMES = (
    "Kod",
    "Tarih",
    "Bölünme Sonrası Sermaye (TL)",
    "Bedelli Oran (%)",
    "Bedelli Nom. Tutar (TL)",
    "Bedelsiz IK Oran (%)",
    "Nakit Tem.Brüt (%)",
    "Hisse Başı Brüt (TL)",
)


def _cell_texts(row) -> list[str]:
    """Cell text with element boundaries kept as spaces.

    The vendor splits labels into several elements (``Kapanış`` + ``(TL)``), so
    ``text_content()`` alone yields ``Kapanış(TL)`` and no header would match.
    """
    return [" ".join(" ".join(cell.itertext()).split()) for cell in row.xpath("./td|./th")]


def _field_key(name: str) -> str:
    """Whitespace-free ASCII upper-case key so ``İK`` and ``IK`` compare equal."""
    text = (
        name.replace("İ", "I")
        .replace("ı", "i")
        .replace("Ş", "S")
        .replace("ş", "s")
        .replace("Ğ", "G")
        .replace("ğ", "g")
        .replace("Ü", "U")
        .replace("ü", "u")
        .replace("Ö", "O")
        .replace("ö", "o")
        .replace("Ç", "C")
        .replace("ç", "c")
    )
    return "".join(text.split()).upper()


def parse_corporate_action_rows(html_text: str) -> list[dict[str, str]]:
    """Raw cell values of the "Bölünme / Temettü" table, keyed by header name.

    lxml is used instead of ``pandas.read_html`` because pandas applies the
    locale separators to the *date* column too (``14.01.2026`` -> 14012026) and
    its ``converters`` argument is ignored for HTML tables. Reading the raw cells
    keeps ``0,8333`` at 0.8333 instead of 8333.
    """
    try:
        document = lxml_html.fromstring(html_text)
    except (ValueError, lxml_html.etree.ParserError):
        return []

    canonical = {_field_key(name): name for name in ACTION_FIELD_NAMES}
    wanted = _field_key("Bedelsiz IK Oran (%)")
    for row in document.iter("tr"):
        header = _cell_texts(row)
        if wanted not in {_field_key(name) for name in header}:
            continue
        tables = row.xpath("ancestor::table[1]")
        if not tables:
            continue
        index = {
            canonical[key]: position
            for position, name in enumerate(header)
            if (key := _field_key(name)) in canonical
        }
        if "Kod" not in index or "Tarih" not in index:
            continue
        out: list[dict[str, str]] = []
        started = False
        for body_row in tables[0].xpath(".//tr"):
            if body_row is row:
                started = True
                continue
            if not started:
                continue
            cells = _cell_texts(body_row)
            if len(cells) != len(header) or cells == header:
                continue
            if not cells[index["Kod"]]:
                continue
            out.append({name: cells[position] for name, position in index.items()})
        return out
    return []


def fetch_corporate_actions(
    session: requests.Session, timeout: int = 60
) -> list[dict[str, object]]:
    """Dividends, bonus issues and rights issues from the public ratios table.

    The vendor table holds the current year only. Returns an empty list on
    failure so the caller keeps stored rows.
    """
    try:
        response = session.get(UNIVERSE_URL, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return []

    out: dict[tuple[str, date, str], dict[str, object]] = {}
    for row in parse_corporate_action_rows(response.text):
        code = str(row.get("Kod", "") or "").strip().upper()
        action_date = _tr_date(row.get("Tarih"))
        if not CODE_RE.fullmatch(code) or action_date is None:
            continue
        ticker = f"{code}.IS"
        cash_per_share = _tr_number(row.get("Hisse Başı Brüt (TL)"))
        cash_ratio = _tr_number(row.get("Nakit Tem.Brüt (%)"))
        bonus_ratio = _tr_number(row.get("Bedelsiz IK Oran (%)"))
        rights_ratio = _tr_number(row.get("Bedelli Oran (%)"))
        rights_amount = _tr_number(row.get("Bedelli Nom. Tutar (TL)"))
        post_capital = _tr_number(row.get("Bölünme Sonrası Sermaye (TL)"))
        common: dict[str, object] = {
            "ticker": ticker,
            "action_date": action_date,
            "cash_per_share_tl": cash_per_share or None,
            "cash_ratio_pct": cash_ratio or None,
            "bonus_ratio_pct": bonus_ratio or None,
            "rights_ratio_pct": rights_ratio or None,
            "rights_amount_tl": rights_amount or None,
            "post_capital_tl": post_capital or None,
            "source": "isyatirim",
        }
        for kind, present in (
            ("temettu", cash_per_share and cash_per_share > 0),
            ("bedelsiz", bonus_ratio and bonus_ratio > 0),
            ("bedelli", rights_ratio and rights_ratio > 0),
        ):
            if present:
                out[(ticker, action_date, kind)] = {**common, "kind": kind}
    return sorted(out.values(), key=lambda item: (str(item["ticker"]), item["action_date"]))


__all__ = [
    "DAILY_COLUMNS",
    "fetch_corporate_actions",
    "fetch_daily",
    "fetch_index_daily",
    "fetch_statements",
    "fetch_universe",
    "parse_corporate_action_rows",
    "published_quarters",
    "statement_available_from",
]
