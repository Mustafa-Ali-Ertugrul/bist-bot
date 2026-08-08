"""Haber botu yardımcı fonksiyonları."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dateutil import parser as date_parser
from sqlalchemy import text
from sqlalchemy.orm import Session

from bist_bot.app_logging import get_logger

logger = get_logger("newsbot.utils")

_STRIP_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "fbclid",
        "ref",
        "source",
        "campaign_id",
        "gclid",
        "click_id",
    }
)


def clean_text(text: str) -> str:
    """HTML taglarını ve fazla boşlukları temizler."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_content_hash(url: str, title: str, content: str) -> str:
    """Haberin benzersiz parmak izini (SHA-256) oluşturur.

    Aynı URL veya aynı başlık+içerik kombinasyonu aynı hash'i üretir.
    """
    raw = f"{url}|{title}|{content}".strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    """URL'deki tracking parametrelerini ve fragment'ı temizler.

    Aynı haberin RSS linki utm_* gibi parametrelerle farklı görünse bile
    aynı canonical URL'ye eşlenir; sonuçta aynı SHA-256 hash'i üretilir.
    """
    if not url:
        return url
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {k: v for k, v in query_params.items() if k.lower() not in _STRIP_PARAMS}
    new_query = urlencode(filtered, doseq=True)
    cleaned = parsed._replace(query=new_query, fragment="")
    return urlunparse(cleaned)


def parse_rss_date(value: str | None) -> datetime | None:
    """RSS/Atom yayın tarihini UTC'ye çevirir (dateutil tabanlı).

    - RFC 2822:   "Wed, 05 Aug 2026 18:08:37 +0000"
    - ISO 8601:   "2026-08-08T06:45:00+03:00" (UTC'ye çevrilir)
    - Naive:      "2026-08-08 06:02:54" (UTC varsayılır)

    SQLite karşılaştırmaları naive datetime beklediğinden tzinfo çıkarılır.
    """
    if not value:
        return None
    value = value.strip()
    try:
        dt = date_parser.parse(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(tzinfo=None)


def check_cross_site_duplicate_fts(
    session: Session,
    title: str,
    current_source_id: int,
    window_hours: float = 24.0,
) -> int | None:
    """FTS5 tablosunda son N saat içinde farklı kaynakta benzer haber ara.

    Başlığın ilk 6 kelimesi phrase (tam ifade) olarak eşleştirilir; FTS5
    ``unicode61 remove_diacritics`` tokenizer'ı kâr/kar gibi diacritic
    farklarını giderir. Eşleşen ilk makalenin id'sini döndürür, yoksa None.
    """
    if not title:
        return None

    words = title.split()[:6]
    if not words:
        return None

    search_phrase = '"' + " ".join(words) + '"'
    sql = text(
        """
        SELECT a.id
        FROM newsbot_articles_fts
        JOIN newsbot_articles a ON a.id = newsbot_articles_fts.rowid
        WHERE newsbot_articles_fts MATCH :query
          AND a.source_id != :current_source_id
          AND a.detected_at >= datetime('now', :window)
        LIMIT 1
        """
    )

    try:
        result = session.execute(
            sql,
            {
                "query": search_phrase,
                "current_source_id": current_source_id,
                "window": f"-{int(window_hours)} hours",
            },
        ).fetchone()
        return result[0] if result else None
    except Exception as exc:
        logger.error("fts5_query_failed", error=str(exc))
        return None
