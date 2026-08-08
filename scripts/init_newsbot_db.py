"""Haber botu DB şemasını kurar ve kaynakları seed eder.

Çalıştırma:
    python scripts/init_newsbot_db.py

Docker'da PYTHONPATH=/app/src zaten ayarlıdır.
"""

from __future__ import annotations

import json
import sys

from sqlalchemy import text

from bist_bot.app_logging import configure_logging
from bist_bot.db.database import DatabaseManager
from bist_bot.newsbot.entities import load_symbols
from bist_bot.newsbot.schema import init_newsbot_schema
from bist_bot.newsbot.sources import load_sources


def _get_logger(name: str):
    from bist_bot.app_logging import get_logger

    return get_logger(name, component="newsbot.init")


def seed_sources(db: DatabaseManager) -> int:
    sources = load_sources()
    upsert_sql = text("""
        INSERT INTO newsbot_sources
            (name, url, source_type, trust_score, scrape_interval_seconds, is_active)
        VALUES (:name, :url, :type, :trust_score, :interval_seconds, :is_active)
        ON CONFLICT(name) DO UPDATE SET
            url                       = excluded.url,
            source_type               = excluded.source_type,
            trust_score               = excluded.trust_score,
            scrape_interval_seconds   = excluded.scrape_interval_seconds,
            is_active                 = excluded.is_active
    """)

    with db.engine.begin() as conn:
        for s in sources:
            conn.execute(
                upsert_sql,
                {
                    "name": s["name"],
                    "url": s["url"],
                    "type": s.get("type", "news"),
                    "trust_score": s["trust_score"],
                    "interval_seconds": s["interval_seconds"],
                    "is_active": 1 if s["active"] else 0,
                },
            )
    return len(sources)


def seed_symbols(db: DatabaseManager) -> int:
    symbols = load_symbols()
    upsert_sql = text("""
        INSERT INTO newsbot_symbols (symbol, company_name, aliases_json, sector, is_active)
        VALUES (:symbol, :company_name, :aliases_json, :sector, 1)
        ON CONFLICT(symbol) DO UPDATE SET
            company_name = excluded.company_name,
            aliases_json = excluded.aliases_json,
            sector       = excluded.sector,
            is_active    = 1
    """)

    with db.engine.begin() as conn:
        for symbol, meta in symbols.items():
            conn.execute(
                upsert_sql,
                {
                    "symbol": symbol,
                    "company_name": meta["company_name"],
                    "aliases_json": json.dumps(meta["aliases"], ensure_ascii=False),
                    "sector": meta.get("sector"),
                },
            )
    return len(symbols)


def main() -> None:
    configure_logging()
    logger = _get_logger("newsbot.init")

    db = DatabaseManager()
    init_newsbot_schema(db.engine)

    n_sources = seed_sources(db)
    n_symbols = seed_symbols(db)

    with db.engine.connect() as conn:
        total_sources = conn.execute(text("SELECT COUNT(*) FROM newsbot_sources")).scalar_one()
        total_symbols = conn.execute(text("SELECT COUNT(*) FROM newsbot_symbols")).scalar_one()

    logger.info(
        "newsbot_db_initialized",
        seeded_sources=n_sources,
        seeded_symbols=n_symbols,
        total_sources=total_sources,
        total_symbols=total_symbols,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
