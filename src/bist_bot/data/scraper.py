"""Resilient scraping helpers for Borsa Istanbul quote acquisition."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Protocol

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class RateLimiterProtocol(Protocol):
    def wait_if_needed(self, domain: str) -> None: ...


@dataclass(frozen=True)
class ScrapeQuoteResult:
    success: bool
    price: float | None = None
    change_percent: float | None = None
    source: str = "borsaistanbul.com"
    detail: str = ""

    def to_payload(self) -> dict[str, float | str] | None:
        if not self.success or self.price is None:
            return None
        return {
            "price": self.price,
            "change_percent": self.change_percent if self.change_percent is not None else 0.0,
            "source": self.source,
        }


def _parse_number(raw: str) -> float | None:
    """Parse Turkish-formatted numeric fragments scraped from HTML."""
    cleaned = raw.strip().replace("%", "").replace("\u00a0", " ")
    cleaned = cleaned.replace(".", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9+\-.]", "", cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_quote_from_text(blob: str) -> tuple[float | None, float | None]:
    price_match = re.search(
        r"(?:Son(?:\s+Değer|\s+Fiyat)?|LastPrice|price)\D*?([0-9]{1,3}(?:[\.,][0-9]{3})*(?:[\.,][0-9]{2}))",
        blob,
        re.IGNORECASE,
    )
    change_match = re.search(
        r"(?:Değişim%|Degisim%|changePercent|change_percent|Bugün\s*\(%\))\D*?([+-]?[0-9]{1,3}(?:[\.,][0-9]{1,2})?)",
        blob,
        re.IGNORECASE,
    )

    price = _parse_number(price_match.group(1)) if price_match else None
    change_percent = _parse_number(change_match.group(1)) if change_match else None
    return price, change_percent


def _extract_quote_from_html(html: str) -> ScrapeQuoteResult:
    if not html.strip():
        return ScrapeQuoteResult(success=False, detail="bos-govde")

    soup = BeautifulSoup(html, "html.parser")
    text_blobs = [soup.get_text(" ", strip=True)]
    text_blobs.extend(script.get_text(" ", strip=True) for script in soup.find_all("script"))
    non_empty_blobs = [blob for blob in text_blobs if blob]

    if not non_empty_blobs:
        return ScrapeQuoteResult(success=False, detail="bos-html-yapisi")

    for blob in non_empty_blobs:
        price, change_percent = _extract_quote_from_text(blob)
        if price is not None:
            return ScrapeQuoteResult(success=True, price=price, change_percent=change_percent)

    return ScrapeQuoteResult(success=False, detail="fiyat-alani-bulunamadi")


def scrape_bist_quote(ticker: str, rate_limiter: RateLimiterProtocol) -> ScrapeQuoteResult:
    """Try to scrape a quote from Borsa Istanbul without raising upstream."""
    symbol = ticker.replace(".IS", "").upper()
    candidate_urls = [
        f"https://www.borsaistanbul.com/tr/sirketler/islem-goren-sirketler/sirket-bilgileri?kod={symbol}",
        f"https://www.borsaistanbul.com/tr/sirketler/sirket-karti?kod={symbol}",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    last_failure = "istek-yapilmadi"

    for url in candidate_urls:
        try:
            rate_limiter.wait_if_needed("borsaistanbul.com.tr")
            response = requests.get(url, timeout=10, headers=headers)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            last_failure = f"timeout:{url}"
            logger.warning("Scrape timeout (%s): %s", symbol, url)
            continue
        except requests.exceptions.RequestException as exc:
            last_failure = f"ag-hatasi:{url}"
            logger.warning("Scrape request failed (%s): %s", symbol, exc)
            continue

        result = _extract_quote_from_html(response.text)
        if result.success:
            logger.info("Scraped realtime quote succeeded (%s) from %s", symbol, url)
            return result

        last_failure = f"parse-hatasi:{result.detail}"
        logger.warning(
            "Scrape parse failed (%s): %s [%s]",
            symbol,
            result.detail,
            url,
        )

    return ScrapeQuoteResult(success=False, detail=last_failure)
