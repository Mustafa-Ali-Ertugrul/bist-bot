"""Haber botu şema testleri — idempotency ve tablo varlığı."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture()
def tmp_db(tmp_path: Path):
    """Geçici SQLite veritabanı döndürür; dosya yolu döner."""
    db_file = tmp_path / "test_newsbot.sqlite"
    return f"sqlite:///{db_file}"


def test_schema_creation_and_idempotency(tmp_db: str):
    engine = create_engine(tmp_db)

    from bist_bot.newsbot.schema import init_newsbot_schema

    # İlk kurulum
    init_newsbot_schema(engine)

    # İkinci kurulum (idempotent olmalı — hata vermemeli)
    init_newsbot_schema(engine)

    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'newsbot_%'")
        ).fetchall()
        names = {row[0] for row in tables}

    expected = {
        "newsbot_sources",
        "newsbot_articles",
        "newsbot_symbols",
        "newsbot_article_entities",
        "newsbot_article_layers",
        "newsbot_layer_scores",
        "newsbot_notifications",
        "newsbot_duplicate_groups",
        "newsbot_keyword_weights",
        "newsbot_feedback_log",
        "newsbot_articles_fts",
    }
    # FTS5 shadow tabloları da newsbot_* önekiyle göründüğünden subset kontrolü yapılır
    assert expected.issubset(names), f"Eksik tablolar: {expected - names}"


def test_upsert_idempotency(tmp_db: str):
    engine = create_engine(tmp_db)

    from bist_bot.newsbot.schema import init_newsbot_schema

    init_newsbot_schema(engine)

    upsert_sql = text("""
        INSERT INTO newsbot_sources
            (name, url, source_type, trust_score, scrape_interval_seconds, is_active)
        VALUES ('kap', 'https://kap.org.tr', 'official', 100, 60, 1)
        ON CONFLICT(name) DO UPDATE SET url = excluded.url
    """)

    with engine.begin() as conn:
        conn.execute(upsert_sql)
        conn.execute(upsert_sql)  # ikinci kez — duplicate olmamalı
        count = conn.execute(
            text("SELECT COUNT(*) FROM newsbot_sources WHERE name = 'kap'")
        ).scalar_one()

    assert count == 1, "Upsert duplicate yaratıyor"


def test_indexes_exist(tmp_db: str):
    engine = create_engine(tmp_db)

    from bist_bot.newsbot.schema import init_newsbot_schema

    init_newsbot_schema(engine)

    with engine.connect() as conn:
        indexes = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
        ).fetchall()
        idx_names = {row[0] for row in indexes}

    required = {
        "idx_newsbot_articles_source_id",
        "idx_newsbot_articles_content_hash",
        "idx_newsbot_entities_article_id",
        "idx_newsbot_scores_article_id",
        "idx_newsbot_notifications_article_id",
    }
    assert required.issubset(idx_names), f"Eksik indeksler: {required - idx_names}"


def test_fts5_exists_and_trigger_sync(tmp_db: str):
    """FTS5 tablosu kurulur ve insert sonrası trigger ile senkronize olur."""
    engine = create_engine(tmp_db)

    from bist_bot.newsbot.schema import init_newsbot_schema

    init_newsbot_schema(engine)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO newsbot_sources (name, url) VALUES ('test', 'test.com')"))
        source_id = conn.execute(
            text("SELECT id FROM newsbot_sources WHERE name='test'")
        ).scalar_one()

        conn.execute(
            text("""
                INSERT INTO newsbot_articles (source_id, url, title, content, content_hash)
                VALUES (:sid, 'url1', 'THY kâr açıkladı', 'İçerik', 'hash1')
            """),
            {"sid": source_id},
        )

        count = conn.execute(text("SELECT COUNT(*) FROM newsbot_articles_fts")).scalar_one()

    assert count == 1, "FTS5 trigger sync failed"
