"""Investing Türkiye haber scraper'ı (RSS)."""

from __future__ import annotations

from .base import RssScraper


class InvestingTrScraper(RssScraper):
    """tr.investing.com haber akışını RSS'ten çeker.

    Ana site bot korumalı (403) olduğundan RSS endpoint'i kullanılır.
    """

    RSS_URL = "https://tr.investing.com/rss/news.rss"
    MAX_ITEMS = 30
