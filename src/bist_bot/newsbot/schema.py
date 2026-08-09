"""Idempotent haber botu şeması (CREATE TABLE IF NOT EXISTS).

Mevcut ``DatabaseManager`` altyapısını kullanır; yeni bir bağlantı kodu yazmaz.
SQLAlchemy 2.0 uyumlu: ``exec_driver_sql`` ile raw SQL doğrudan SQLite driver'ına
iletilir — birden fazla statement '; ile ayrılmış şekilde tek seferde çalışır.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

from bist_bot.app_logging import get_logger

logger = get_logger("newsbot.schema")

NEWSBOT_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS newsbot_sources (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT UNIQUE NOT NULL,
    url                TEXT NOT NULL,
    source_type        TEXT DEFAULT 'news',
    trust_score        INTEGER DEFAULT 70,
    scrape_interval_seconds INTEGER DEFAULT 120,
    is_active          INTEGER DEFAULT 1,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS newsbot_articles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         INTEGER NOT NULL,
    url               TEXT,
    canonical_url     TEXT,
    title             TEXT,
    content           TEXT,
    summary           TEXT,
    published_at      TEXT,
    detected_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    language          TEXT DEFAULT 'tr',
    content_hash      TEXT UNIQUE,
    is_duplicate      INTEGER DEFAULT 0,
    original_article_id  INTEGER,
    trust_score       INTEGER,
    raw_payload       TEXT,
    FOREIGN KEY (source_id) REFERENCES newsbot_sources(id)
);

CREATE TABLE IF NOT EXISTS newsbot_symbols (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT UNIQUE NOT NULL,
    company_name  TEXT,
    aliases_json  TEXT,
    sector        TEXT,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS newsbot_article_entities (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id        INTEGER NOT NULL,
    symbol_id         INTEGER NOT NULL,
    match_type        TEXT,
    match_confidence  INTEGER,
    matched_text      TEXT,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id)  REFERENCES newsbot_articles(id),
    FOREIGN KEY (symbol_id)   REFERENCES newsbot_symbols(id)
);

CREATE TABLE IF NOT EXISTS newsbot_article_layers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER NOT NULL,
    layer           TEXT NOT NULL,
    category        TEXT,
    primary_layer   INTEGER DEFAULT 0,
    confidence      INTEGER,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES newsbot_articles(id)
);

CREATE TABLE IF NOT EXISTS newsbot_layer_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER NOT NULL,
    layer           TEXT NOT NULL,
    symbol_id       INTEGER,
    scope           TEXT,
    direction       TEXT,
    score_1_10      INTEGER,
    impact_level    TEXT,
    confidence      INTEGER,
    keywords_json   TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES newsbot_articles(id),
    FOREIGN KEY (symbol_id)  REFERENCES newsbot_symbols(id)
);

CREATE TABLE IF NOT EXISTS newsbot_notifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id          INTEGER NOT NULL,
    layer               TEXT,
    symbol_id           INTEGER,
    telegram_chat_id    TEXT,
    telegram_message_id TEXT,
    payload_json        TEXT,
    sent_at             TEXT,
    status              TEXT,
    FOREIGN KEY (article_id)  REFERENCES newsbot_articles(id),
    FOREIGN KEY (symbol_id)   REFERENCES newsbot_symbols(id)
);

CREATE TABLE IF NOT EXISTS newsbot_duplicate_groups (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    group_key          TEXT UNIQUE NOT NULL,
    first_article_id   INTEGER,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at         TEXT,
    FOREIGN KEY (first_article_id) REFERENCES newsbot_articles(id)
);

CREATE TABLE IF NOT EXISTS newsbot_keyword_weights (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword        TEXT NOT NULL,
    layer          TEXT NOT NULL,
    category       TEXT,
    polarity       TEXT,
    base_weight    REAL DEFAULT 1.0,
    current_weight REAL DEFAULT 1.0,
    updated_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(keyword, layer, category)
);

CREATE TABLE IF NOT EXISTS newsbot_feedback_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id           INTEGER NOT NULL,
    symbol_id            INTEGER,
    predicted_direction  TEXT,
    predicted_score      INTEGER,
    predicted_impact     TEXT,
    actual_direction     TEXT,
    actual_score         INTEGER,
    actual_impact        TEXT,
    error_value          REAL,
    feedback_type        TEXT,
    created_at           TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES newsbot_articles(id),
    FOREIGN KEY (symbol_id)  REFERENCES newsbot_symbols(id)
);

CREATE TABLE IF NOT EXISTS newsbot_price_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id    INTEGER NOT NULL,
    symbol_id     INTEGER NOT NULL,
    horizon       TEXT NOT NULL,
    price         REAL NOT NULL,
    captured_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES newsbot_articles(id),
    FOREIGN KEY (symbol_id)  REFERENCES newsbot_symbols(id),
    UNIQUE(article_id, symbol_id, horizon)
);

CREATE VIRTUAL TABLE IF NOT EXISTS newsbot_articles_fts USING fts5(
    title,
    content,
    content=newsbot_articles,
    content_rowid=id,
    tokenize="unicode61 remove_diacritics 1"
);
CREATE TRIGGER IF NOT EXISTS newsbot_articles_ai AFTER INSERT ON newsbot_articles BEGIN INSERT INTO newsbot_articles_fts(rowid, title, content) VALUES (new.id, new.title, new.content); END;
CREATE TRIGGER IF NOT EXISTS newsbot_articles_ad AFTER DELETE ON newsbot_articles BEGIN INSERT INTO newsbot_articles_fts(newsbot_articles_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content); END;
CREATE TRIGGER IF NOT EXISTS newsbot_articles_au AFTER UPDATE ON newsbot_articles BEGIN INSERT INTO newsbot_articles_fts(newsbot_articles_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content); INSERT INTO newsbot_articles_fts(rowid, title, content) VALUES (new.id, new.title, new.content); END;

CREATE INDEX IF NOT EXISTS idx_newsbot_articles_source_id      ON newsbot_articles(source_id);
CREATE INDEX IF NOT EXISTS idx_newsbot_articles_content_hash   ON newsbot_articles(content_hash);
CREATE INDEX IF NOT EXISTS idx_newsbot_entities_article_id     ON newsbot_article_entities(article_id);
CREATE INDEX IF NOT EXISTS idx_newsbot_scores_article_id       ON newsbot_layer_scores(article_id);
CREATE INDEX IF NOT EXISTS idx_newsbot_notifications_article_id ON newsbot_notifications(article_id);
CREATE INDEX IF NOT EXISTS idx_newsbot_snapshots_article_symbol ON newsbot_price_snapshots(article_id, symbol_id);
"""


def init_newsbot_schema(engine: Engine) -> None:
    """Tabloları idempotent olarak kur (varsa atla). Mevcut tablolara dokunmaz."""
    import re

    # SQLite driver birden fazla statement'ı tek seferde kabul etmez;
    # statement'ları ; ile ayırıp teker teker çalıştırır.
    statements = [s.strip() for s in re.split(r";\s*\n", NEWSBOT_SCHEMA_SQL) if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.exec_driver_sql(stmt)
        # FTS5 index'ini içerik tablosundan yeniden inşa et (backfill, idempotent).
        # Eski kayıtlar bu sayede cross-site dedup penceresine dahil olur.
        try:
            conn.exec_driver_sql(
                "INSERT INTO newsbot_articles_fts(newsbot_articles_fts) VALUES('rebuild');"
            )
        except Exception as exc:
            logger.warning("fts_rebuild_failed", error=str(exc))
