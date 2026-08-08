"""Borsa İstanbul duyuru scraper'ı (RSS)."""

from __future__ import annotations

from .base import RssScraper


class BorsaIstanbulScraper(RssScraper):
    """Borsa İstanbul duyuru/haber akışını RSS'ten çeker."""

    RSS_URL = "https://www.borsaistanbul.com/rss.xml"
    MAX_ITEMS = 30
