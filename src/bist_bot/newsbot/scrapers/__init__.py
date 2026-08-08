"""Haber scraper registry — yeni adaptörler buraya eklenir."""

from __future__ import annotations

from .base import BaseScraper, RssScraper
from .bloomberght import BloombergHtScraper
from .borsa_istanbul import BorsaIstanbulScraper
from .foreks import ForeksScraper
from .investing_tr import InvestingTrScraper
from .kap import KapScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    "kap": KapScraper,
    "borsaistanbul": BorsaIstanbulScraper,
    "foreks": ForeksScraper,
    "bloomberght": BloombergHtScraper,
    "investing_tr": InvestingTrScraper,
}

__all__ = [
    "SCRAPER_REGISTRY",
    "BaseScraper",
    "BloombergHtScraper",
    "BorsaIstanbulScraper",
    "ForeksScraper",
    "InvestingTrScraper",
    "KapScraper",
    "RssScraper",
]
