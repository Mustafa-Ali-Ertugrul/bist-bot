"""BloombergHT haber scraper'ı (RSS)."""

from __future__ import annotations

from .base import RssScraper


class BloombergHtScraper(RssScraper):
    """BloombergHT haber akışını RSS'ten çeker."""

    RSS_URL = "https://www.bloomberght.com/rss/"
    MAX_ITEMS = 30
