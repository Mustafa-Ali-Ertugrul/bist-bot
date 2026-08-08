"""Cross-site dedup integration testi — gerçek SQLite DB + save_articles."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from bist_bot.newsbot.collector import save_articles
from bist_bot.newsbot.models import NewsbotArticle, NewsbotSource
from bist_bot.newsbot.schema import init_newsbot_schema
from bist_bot.newsbot.utils import check_cross_site_duplicate_fts


@pytest.fixture()
def newsbot_db(tmp_path: Path):
    """Temiz newsbot şeması + iki kaynak içeren oturum."""
    engine = create_engine(f"sqlite:///{tmp_path / 'newsbot.db'}")
    init_newsbot_schema(engine)
    session = Session(engine)

    foreks = NewsbotSource(
        name="foreks",
        url="https://www.foreks.com",
        source_type="news",
        trust_score=80,
        scrape_interval_seconds=90,
        is_active=1,
    )
    bloomberght = NewsbotSource(
        name="bloomberght",
        url="https://www.bloomberght.com",
        source_type="news",
        trust_score=75,
        scrape_interval_seconds=120,
        is_active=1,
    )
    session.add_all([foreks, bloomberght])
    session.commit()
    yield session, engine, foreks, bloomberght
    session.close()
    engine.dispose()


def test_cross_site_duplicate_flagged(newsbot_db):
    """Aynı haber ikinci kaynaktan gelince is_duplicate + original_article_id işaretlenir."""
    session, _engine, foreks, bloomberght = newsbot_db

    foreks_article = {
        "url": "https://www.foreks.com/haber/detay/koc-holding-net-kar-elde-etti",
        "title": "Koç Holding net kâr elde etti, beklentilerin üzerinde",
        "content": "Koç Holding ikinci çeyrekte 19,7 milyar TL net kâr açıkladı.",
        "published_at": datetime.now(UTC),
    }
    save_articles(session, [foreks_article], foreks)
    session.flush()

    # Aynı haber bloomberght'ten (başlık küçük farkla, farklı URL)
    bloomberght_article = {
        "url": "https://www.bloomberght.com/koc-holding-net-kar-elde-etti",
        "title": "Koç Holding net kar elde etti, beklentilerin üzerinde",
        "content": "Koç Holding açıklamasına göre kâr beklentileri aştı.",
        "published_at": datetime.now(UTC),
    }
    save_articles(session, [bloomberght_article], bloomberght)
    session.flush()

    articles = session.execute(select(NewsbotArticle)).scalars().all()
    assert len(articles) == 2, "Her iki kaynak makalesi de saklanmalı"

    flagged = [a for a in articles if a.is_duplicate == 1]
    assert len(flagged) == 1
    dup = flagged[0]
    original = next(a for a in articles if a.id == dup.original_article_id)
    assert dup.source_id == bloomberght.id
    assert original.source_id == foreks.id
    assert dup.canonical_url == original.url


def test_distinct_news_not_flagged(newsbot_db):
    """Farklı konulardaki haberler duplicate işaretlenmez."""
    session, _engine, foreks, bloomberght = newsbot_db

    save_articles(
        session,
        [
            {
                "url": "https://www.foreks.com/haber/detay/enflasyon-verileri",
                "title": "Türkiye'de enflasyon verileri açıklandı",
                "content": "TÜİK ağustos enflasyonunu açıkladı.",
                "published_at": datetime.now(UTC),
            }
        ],
        foreks,
    )
    save_articles(
        session,
        [
            {
                "url": "https://www.bloomberght.com/aselsan-sozlesme",
                "title": "ASELSAN yeni sözleşme imzaladı",
                "content": "ASELSAN ihracat sözleşmesi duyurdu.",
                "published_at": datetime.now(UTC),
            }
        ],
        bloomberght,
    )
    session.flush()

    articles = session.execute(select(NewsbotArticle)).scalars().all()
    assert len(articles) == 2
    assert all(a.is_duplicate == 0 for a in articles)
    assert all(a.original_article_id is None for a in articles)


def test_same_source_repeat_is_hash_dup(newsbot_db):
    """Aynı kaynaktan aynı makale tekrar gelirse kaydedilmez (hash dedup)."""
    session, _engine, foreks, _bloomberght = newsbot_db

    article = {
        "url": "https://www.foreks.com/haber/detay/tekrar",
        "title": "Tekrar eden haber başlığı",
        "content": "içerik",
        "published_at": datetime.now(UTC),
    }
    save_articles(session, [article], foreks)
    save_articles(session, [article], foreks)
    session.flush()

    articles = session.execute(select(NewsbotArticle)).scalars().all()
    assert len(articles) == 1


def test_fts5_detects_diacritic_equivalent(tmp_path):
    """FTS5 remove_diacritics: kâr/kar eşleşir; aynı kaynak eşleşmez."""
    db_url = f"sqlite:///{tmp_path / 'test_dedup.sqlite'}"
    engine = create_engine(db_url)
    init_newsbot_schema(engine)

    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO newsbot_sources (name, url) VALUES ('foreks', 'f.com'), ('bloomberght', 'b.com')"
            )
        )
        foreks_id = session.execute(
            text("SELECT id FROM newsbot_sources WHERE name='foreks'")
        ).scalar_one()
        bloomberg_id = session.execute(
            text("SELECT id FROM newsbot_sources WHERE name='bloomberght'")
        ).scalar_one()

        session.execute(
            text("""
                INSERT INTO newsbot_articles (source_id, url, title, content, content_hash, detected_at)
                VALUES (:sid, 'url1', 'THY kâr açıkladı', 'Şirket net kârını artırdı', 'hash1', datetime('now'))
            """),
            {"sid": foreks_id},
        )
        session.commit()

        orig_id = check_cross_site_duplicate_fts(session, "THY kar açıkladı", bloomberg_id, 24)

        assert orig_id is not None, "FTS5 failed to match diacritic equivalent"

        orig_id_same_source = check_cross_site_duplicate_fts(
            session, "THY kâr açıkladı", foreks_id, 24
        )
        assert orig_id_same_source is None, "Same source should not trigger cross-site dedup"
