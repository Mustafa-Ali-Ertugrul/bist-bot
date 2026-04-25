"""Realtime quote and watchlist helper functions for market data fetching."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Protocol

import requests

from bist_bot.data.bist100 import BIST100_TICKERS
from bist_bot.data.helpers import clean_ticker_list
from bist_bot.data.scraper import _parse_number, scrape_bist_quote

logger = logging.getLogger(__name__)

_BIST100_CACHE: list[str] | None = None
_BIST100_CACHE_TIME: datetime | None = None


class RateLimiter:
    """Basit domain-bazli rate limiter."""

    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self.last_request: dict[str, float] = {}

    def wait_if_needed(self, domain: str) -> None:
        current_time = time.time()
        last_request = self.last_request.get(domain)
        if last_request is not None:
            elapsed = current_time - last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self.last_request[domain] = time.time()


class RateLimiterProtocol(Protocol):
    def wait_if_needed(self, domain: str) -> None: ...


def parse_tr_number(raw: str) -> float | None:
    """Parse Turkish-formatted numeric text into a float."""
    return _parse_number(raw)


def get_price_from_bist_website(
    ticker: str, rate_limiter: RateLimiterProtocol
) -> dict[str, float | str] | None:
    """Fetch a near real-time quote from the Borsa Istanbul website."""
    return scrape_bist_quote(ticker, rate_limiter).to_payload()


def get_bist100_tickers(
    rate_limiter: RateLimiterProtocol, force_refresh: bool = False
) -> list[str]:
    """Build the watchlist ticker set with cache and fallback support."""
    global _BIST100_CACHE, _BIST100_CACHE_TIME

    if not force_refresh:
        cached = _BIST100_CACHE
        cached_time = _BIST100_CACHE_TIME
        if cached and cached_time and (datetime.now() - cached_time).total_seconds() < 3600:
            logger.info(f"Demo/watchlist cache hit: {len(cached)} tickers")
            return cached

    tickers: list[str] = []

    try:
        rate_limiter.wait_if_needed("yahoo.finance")
        response = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=true&lang=tr-TR&region=TR&scrIds=day_gainers&start=0&count=10",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("finance", {}).get("result", [])
            if results:
                for item in results[0].get("quotes", []):
                    symbol = item.get("symbol", "")
                    if symbol and not symbol.endswith(".IS"):
                        symbol = symbol + ".IS"
                    if symbol.endswith(".IS"):
                        tickers.append(symbol)
    except Exception as exc:
        logger.warning(f"Demo/watchlist dynamic fetch hatasi: {exc}")

    tickers = clean_ticker_list(tickers)

    if len(tickers) >= 50:
        _BIST100_CACHE = tickers
        _BIST100_CACHE_TIME = datetime.now()
        logger.info(f"Demo/watchlist dynamic yüklendi: {len(tickers)} hisse")
        return tickers

    logger.info(f"Demo/watchlist dynamic yetersiz ({len(tickers)}), fallback kullaniliyor")
    if BIST100_TICKERS:
        fallback_clean = clean_ticker_list(BIST100_TICKERS)
        _BIST100_CACHE = fallback_clean
        _BIST100_CACHE_TIME = datetime.now()
        return fallback_clean

    _BIST100_CACHE = []
    _BIST100_CACHE_TIME = datetime.now()
    return []
