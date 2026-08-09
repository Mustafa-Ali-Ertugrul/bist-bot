"""Haber toplayıcı: kaynaklardan çeker, dedup eder, şirket varlıklarını işaretler.

Docker'da ``python -m bist_bot.newsbot.collector`` olarak çalışır; her kaynağı
kendi ``interval_seconds`` değerine göre periyodik olarak tarar.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from bist_bot.app_logging import configure_logging, get_logger
from bist_bot.config.settings import settings
from bist_bot.db.database import DatabaseManager
from bist_bot.newsbot.entities import EntityExtractor, load_symbols
from bist_bot.newsbot.feedback import evaluate_due_feedback
from bist_bot.newsbot.models import NewsbotArticle, NewsbotSource
from bist_bot.newsbot.notifier import NewsbotNotifier
from bist_bot.newsbot.price_snapshot import PriceSnapshotService
from bist_bot.newsbot.schema import init_newsbot_schema
from bist_bot.newsbot.scorer import (
    calculate_score,
    classify_layer,
    load_keywords,
    save_layer_scores,
)
from bist_bot.newsbot.scrapers import SCRAPER_REGISTRY
from bist_bot.newsbot.sources import load_sources
from bist_bot.newsbot.utils import (
    canonicalize_url,
    check_cross_site_duplicate_fts,
    generate_content_hash,
)

logger = get_logger("newsbot.collector", component="newsbot.collector")

_DEDUP_WINDOW_HOURS = 24


def save_articles(
    session: Session,
    articles: list[dict],
    source: NewsbotSource,
) -> tuple[int, int, int]:
    """Makaleleri kaydeder; content_hash ve FTS5 tabanlı dedup uygular.

    - ``content_hash`` daha önce kaydedildiyse makale atlanır (``dup``).
    - Farklı kaynakta son ``_DEDUP_WINDOW_HOURS`` saat içinde aynı başlık varsa
      makale duplicate işaretlenir ve ``canonical_url`` orijinal makalenin
      url'ine eşitlenir (``cross_dup``).

    Döner: ``(new, dup, cross_dup)`` sayıları.
    """
    new = dup = cross_dup = 0
    for item in articles:
        url = canonicalize_url(item.get("url") or "")
        title = (item.get("title") or "").strip()
        content = item.get("content") or ""
        published_at = item.get("published_at")
        content_hash = generate_content_hash(url, title, content)

        existing = session.execute(
            select(NewsbotArticle.id).where(NewsbotArticle.content_hash == content_hash)
        ).scalar_one_or_none()
        if existing is not None:
            dup += 1
            continue

        original_id = check_cross_site_duplicate_fts(session, title, source.id, _DEDUP_WINDOW_HOURS)
        is_duplicate = 1 if original_id is not None else 0
        canonical_url = url
        if original_id is not None:
            cross_dup += 1
            original = session.get(NewsbotArticle, original_id)
            if original is not None and original.url:
                canonical_url = original.url

        article = NewsbotArticle(
            source_id=source.id,
            url=url,
            canonical_url=canonical_url,
            title=title,
            content=content,
            summary=None,
            published_at=published_at,
            detected_at=datetime.now(UTC),
            language="tr",
            content_hash=content_hash,
            is_duplicate=is_duplicate,
            original_article_id=original_id,
            trust_score=source.trust_score,
            raw_payload=None,
        )
        session.add(article)
        # Sonraki satırların hash dedup kontrolü görebilmesi için hemen flush.
        session.flush()
        new += 1

    if articles:
        logger.info(
            "articles_saved",
            source=source.name,
            new=new,
            dup=dup,
            cross_dup=cross_dup,
        )
    return new, dup, cross_dup


def store_article_entities(
    session: Session,
    article_id: int,
    symbol_ids: dict[str, int],
    entities: list[dict],
) -> int:
    """Yeni makale için tespit edilen şirketleri newsbot_article_entities'e yazar.

    DB'de seed edilmemiş semboller sessizce atlanır (FK güvenliği).
    """
    inserted = 0
    for entity in entities:
        symbol_id = symbol_ids.get(entity["symbol"])
        if symbol_id is None:
            continue
        session.execute(
            text(
                """
                INSERT INTO newsbot_article_entities
                    (article_id, symbol_id, match_type, match_confidence, matched_text)
                VALUES (:article_id, :symbol_id, :match_type, :confidence, :matched_text)
                """
            ),
            {
                "article_id": article_id,
                "symbol_id": symbol_id,
                "match_type": entity["match_type"],
                "confidence": entity["confidence"],
                "matched_text": entity["raw_match"],
            },
        )
        inserted += 1
    return inserted


def load_extraction_context(
    db: DatabaseManager,
) -> tuple[dict[str, int], EntityExtractor, dict]:
    """DB'deki aktif sembol id'lerini ve config tabanlı extractor + keywords yükler."""
    with db.session_scope(read_only=True) as session:
        rows = session.execute(
            text("SELECT symbol, id FROM newsbot_symbols WHERE is_active = 1")
        ).all()
    symbol_ids = {str(row.symbol): int(row.id) for row in rows}
    extractor = EntityExtractor(load_symbols())
    keywords = load_keywords()
    layer_triggers = keywords.get("layer_triggers", {})
    return symbol_ids, extractor, layer_triggers, keywords


def _store_entities_for_new_articles(
    session: Session,
    db_source: NewsbotSource,
    max_id: int,
    symbol_ids: dict[str, int],
    extractor: EntityExtractor,
    layer_triggers: dict,
    keywords: dict,
    notifier: NewsbotNotifier | None = None,
    snapshot_service: PriceSnapshotService | None = None,
) -> tuple[int, int, int]:
    """max_id sonrası eklenen makaleler için entity + katman/skor kaydeder.

    Döner: ``(entities_inserted, scores_saved, notifications_sent)``
    """
    rows = (
        session.execute(
            select(NewsbotArticle).where(
                NewsbotArticle.source_id == db_source.id,
                NewsbotArticle.id > max_id,
            )
        )
        .scalars()
        .all()
    )
    entities_total = 0
    scores_total = 0
    notif_total = 0
    for row in rows:
        title = row.title or ""
        content = row.content or ""
        entities = extractor.extract_entities(title, content)
        entities_total += store_article_entities(session, row.id, symbol_ids, entities)

        # Skorlama — entities listesi scorer'a doğrudan iletilir (tekrar extract yok)
        symbol_id = next((symbol_ids.get(e["symbol"]) for e in entities), None)
        layer = classify_layer(title, content, entities, layer_triggers)
        score, direction, matched = calculate_score(title, content, layer, keywords)
        save_layer_scores(session, row.id, layer, score, direction, matched, symbol_id)
        if layer != "uncategorized":
            scores_total += 1

        # Bildirim — yalnızca uncategorized olmayan ve eşiği aşan skorlar
        if notifier is not None and layer != "uncategorized":
            sent = notifier.notify(
                session,
                article_id=row.id,
                title=title,
                layer=layer,
                score=score,
                direction=direction,
                source_name=db_source.name,
                symbol=None,  # symbol id DB'de tutulur, burada string gerekli değil
                matched_keywords=matched,
            )
            if sent:
                notif_total += 1

        # Fiyat snapshot — skorlama ile aynı sembol (ilk entity) üzerinden t0
        if snapshot_service is not None and symbol_id is not None:
            symbol = next(
                (e["symbol"] for e in entities if symbol_ids.get(e["symbol"]) == symbol_id),
                None,
            )
            if symbol is not None:
                try:
                    snapshot_service.capture_t0(session, row.id, symbol_id, symbol)
                except Exception as exc:
                    logger.error(
                        "snapshot_capture_failed",
                        article_id=row.id,
                        symbol=symbol,
                        error=str(exc),
                    )

    return entities_total, scores_total, notif_total


def run_once(db: DatabaseManager) -> None:
    """Tüm aktif kaynakları bir kez tarar ve kaydeder."""
    symbol_ids, extractor, layer_triggers, keywords = load_extraction_context(db)
    notifier = NewsbotNotifier(
        token=settings.notification.TELEGRAM_BOT_TOKEN,
        chat_id=settings.notification.TELEGRAM_CHAT_ID,
        min_score=settings.notification.NEWSBOT_MIN_SCORE,
    )
    snapshot_service = PriceSnapshotService()
    source_configs = [s for s in load_sources() if s.get("active", True)]

    for cfg in source_configs:
        name = cfg["name"]
        scraper_cls = SCRAPER_REGISTRY.get(name)
        if scraper_cls is None:
            logger.warning("unknown_scraper", source=name)
            continue
        try:
            scraper = scraper_cls(cfg)
            articles = scraper.fetch_articles()
            if articles:
                with db.session_scope() as session:
                    db_source = session.execute(
                        select(NewsbotSource).where(NewsbotSource.name == name)
                    ).scalar_one_or_none()
                    if db_source is None:
                        logger.warning("source_not_in_db", source=name)
                        continue
                    max_id = (
                        session.execute(
                            select(func.max(NewsbotArticle.id)).where(
                                NewsbotArticle.source_id == db_source.id
                            )
                        ).scalar()
                        or 0
                    )
                    new, dup, cross_dup = save_articles(session, articles, db_source)
                    n_entities, n_scores, n_notifs = _store_entities_for_new_articles(
                        session, db_source, max_id, symbol_ids, extractor, layer_triggers,
                        keywords, notifier, snapshot_service,
                    )
                    if n_entities:
                        logger.info("entities_extracted", source=name, count=n_entities)
                    if n_scores:
                        logger.info("layer_scores_saved", source=name, count=n_scores)
                    if n_notifs:
                        logger.info("notifications_sent", source=name, count=n_notifs)
                    logger.debug(
                        "source_cycle_done",
                        source=name,
                        new=new,
                        dup=dup,
                        cross_dup=cross_dup,
                        entities=n_entities,
                        scores=n_scores,
                        notifications=n_notifs,
                    )
        except Exception as exc:
            logger.error("source_cycle_failed", source=name, error=str(exc))
        time.sleep(cfg.get("interval_seconds", 120))

    # Feedback loop — vadesi gelen 1h/4h/1d snapshotlarını kapat ve yorumla
    try:
        with db.session_scope() as session:
            n_feedback = evaluate_due_feedback(session, snapshot_service)
        if n_feedback:
            logger.info("feedback_evaluated_total", count=n_feedback)
    except Exception as exc:
        logger.error("feedback_cycle_failed", error=str(exc))


def main() -> None:
    configure_logging()
    db = DatabaseManager()
    init_newsbot_schema(db.engine)
    logger.info("collector_started")
    while True:
        try:
            run_once(db)
        except Exception as exc:
            logger.error("collector_cycle_failed", error=str(exc))
        time.sleep(5)


if __name__ == "__main__":
    main()
