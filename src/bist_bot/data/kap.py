"""Anonymous KAP client (Faz A1).

KAP (Kamuyu Aydınlatma Platformu) publishes the current day's disclosure list at
``/tr/api/disclosure/list/light``. The endpoint needs no key or session; it
returns the legal company title, so the caller still has to map it to a BIST
symbol. Historical lists are not exposed there, which is why the sync runs daily
and accumulates history instead of pretending to backfill it.

The disclosure detail page embeds ``stockCode``; ``fetch_stock_code`` reads it
only for rows the title matcher could not resolve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import requests

BASE = "https://www.kap.org.tr"
LIST_URL = f"{BASE}/tr/api/disclosure/list/light"
DETAIL_URL = f"{BASE}/tr/Bildirim/{{index}}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "application/json",
    "Referer": f"{BASE}/tr/bildirim-sorgu",
}
ISTANBUL = ZoneInfo("Europe/Istanbul")
STOCK_CODE_RE = re.compile(r"stockCode[^A-Z0-9]{1,8}([A-Z0-9]{2,6})")


@dataclass(frozen=True)
class KapDisclosure:
    disclosure_index: int
    company_title: str
    subject: str
    summary: str | None
    published_at: datetime
    published_date: date
    url: str
    disclosure_class: str | None = None


def parse_publish_date(raw: object) -> datetime | None:
    """KAP sends ``dd.mm.yyyy HH:MM:SS`` in Istanbul time; store naive UTC."""
    if not isinstance(raw, str):
        return None
    try:
        local = datetime.strptime(raw.strip(), "%d.%m.%Y %H:%M:%S").replace(tzinfo=ISTANBUL)
    except ValueError:
        return None
    return local.astimezone(UTC).replace(tzinfo=None)


def parse_disclosures(payload: object) -> list[KapDisclosure]:
    """Turn the light-list JSON into records, skipping malformed rows."""
    if not isinstance(payload, list):
        return []
    out: dict[int, KapDisclosure] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("disclosureIndex"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        published = parse_publish_date(item.get("publishDate"))
        if published is None or index <= 0:
            continue
        summary = item.get("summary")
        out[index] = KapDisclosure(
            disclosure_index=index,
            company_title=str(item.get("title") or "").strip(),
            subject=str(item.get("subject") or "").strip(),
            summary=str(summary).strip() if summary else None,
            published_at=published,
            published_date=published.date(),
            url=DETAIL_URL.format(index=index),
        )
    return sorted(out.values(), key=lambda row: row.published_at, reverse=True)


def fetch_disclosures(
    session: requests.Session | None = None, *, timeout: int = 30
) -> list[KapDisclosure]:
    """Today's disclosure list. Empty list on network/parse failure (caller keeps old data)."""
    client = session or requests.Session()
    try:
        response = client.get(LIST_URL, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    return parse_disclosures(payload)


def fetch_stock_code(
    index: int, session: requests.Session | None = None, *, timeout: int = 30
) -> str | None:
    """Symbol from a detail page; used only when the title matcher fails."""
    client = session or requests.Session()
    url = DETAIL_URL.format(index=index)
    try:
        response = client.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return None
    match = STOCK_CODE_RE.search(response.text)
    return match.group(1) if match else None


__all__ = [
    "KapDisclosure",
    "fetch_disclosures",
    "fetch_stock_code",
    "parse_disclosures",
    "parse_publish_date",
]
