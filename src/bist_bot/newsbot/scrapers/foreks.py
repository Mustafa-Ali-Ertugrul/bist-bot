"""Foreks haber scraper'ı (RSS)."""

from __future__ import annotations

from .base import RssScraper


class ForeksScraper(RssScraper):
    """Foreks.com haber akışını RSS'ten çeker."""

    RSS_URL = "https://www.foreks.com/rss"
    MAX_ITEMS = 40
