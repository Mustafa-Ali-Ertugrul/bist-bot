"""Newsbot Telegram notifier testleri."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bist_bot.newsbot.notifier import NewsbotNotifier, build_message  # noqa: E402
from bist_bot.newsbot.schema import init_newsbot_schema  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_notifier(min_score: int = 7) -> NewsbotNotifier:
    """Return an enabled notifier (send path is patched per-test)."""
    notifier = NewsbotNotifier(
        token="mock-token",
        chat_id="mock-chat",
        min_score=min_score,
    )
    assert notifier.enabled
    return notifier


@pytest.fixture()
def sample_db(tmp_path):
    """SQLite DB with newsbot schema + one source row."""
    db_path = tmp_path / "test_newsbot.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_newsbot_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO newsbot_sources (name, url, source_type) VALUES (:n, :u, :t)"),
            {"n": "test_src", "u": "https://test.com", "t": "news"},
        )
    return engine


def _insert_article(session: Session, source_id: int, title: str, content: str = "") -> int:
    url = f"https://test.com/{hashlib.sha256(title.encode()).hexdigest()[:8]}"
    h = hashlib.sha256(url.encode()).hexdigest()
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    session.execute(
        text(
            """
            INSERT INTO newsbot_articles
                (source_id, url, canonical_url, title, content, published_at, detected_at,
                 language, content_hash, is_duplicate, trust_score)
            VALUES (:sid, :url, :url, :title, :content, :pub, :det, 'tr', :h, 0, 80)
            """
        ),
        {
            "sid": source_id,
            "url": url,
            "title": title,
            "content": content,
            "pub": now,
            "det": now,
            "h": h,
        },
    )
    return int(session.execute(text("SELECT last_insert_rowid()")).scalar_one())


# ---------------------------------------------------------------------------
# Tests — message building
# ---------------------------------------------------------------------------


def test_build_message_stock_positive():
    msg = build_message(
        title="THYAO kâr artışı açıkladı",
        layer="stock",
        score=7,
        direction="positive",
        source_name="bloomberght",
        symbol="THYAO",
        matched_keywords={"positive": ["kâr artışı"], "negative": []},
    )
    assert "📈" in msg
    assert "[STOCK]" in msg
    assert "THYAO" in msg
    assert "Olumlu" in msg
    assert "Orta" in msg  # score=7 → medium impact
    assert "kâr artışı" in msg
    assert "yatırım tavsiyesi değildir" in msg.lower()


def test_build_message_macro_negative():
    msg = build_message(
        title="TCMB faiz artışı bekleniyor",
        layer="macro",
        score=3,
        direction="negative",
        source_name="foreks",
        matched_keywords={"positive": [], "negative": ["faiz artışı"]},
    )
    assert "🏦" in msg
    assert "[MACRO]" in msg
    assert "faiz artışı" in msg
    assert "Yüksek" in msg  # score=3 → high impact


def test_build_message_no_symbol_generic():
    msg = build_message(
        title="ABD seçim sonuçları piyasa etkiledi",
        layer="global",
        score=5,
        direction="neutral",
        source_name="investing_tr",
        matched_keywords={"positive": [], "negative": []},
    )
    assert "GENEL" in msg
    assert "[GLOBAL]" in msg
    assert "Nötr" in msg
    assert "Düşük" in msg  # score=5 → low impact


def test_build_message_long_title_truncated():
    long_title = "A" * 500
    msg = build_message(
        title=long_title,
        layer="stock",
        score=8,
        direction="positive",
        source_name="kap",
        matched_keywords={"positive": ["rekor"], "negative": []},
    )
    assert len(msg) <= 4096


# ---------------------------------------------------------------------------
# Tests — threshold filtering
# ---------------------------------------------------------------------------


def test_below_threshold_skipped(sample_db):
    notifier = _make_notifier(min_score=7)
    with patch("bist_bot.newsbot.notifier.send_telegram_with_retry") as mock_send:
        with sample_db.begin() as sess:
            sid = sess.execute(text("SELECT id FROM newsbot_sources WHERE name='test_src'")).scalar_one()
            aid = _insert_article(sess, sid, "Faiz kararı açıklandı")
            # score=5 < min_score=7 → no notification, no DB record
            result = notifier.notify(
                sess,
                article_id=aid,
                title="Faiz kararı açıklandı",
                layer="macro",
                score=5,
                direction="neutral",
                source_name="test_src",
                matched_keywords={"positive": [], "negative": []},
            )
            assert result is False
            mock_send.assert_not_called()
            cnt = sess.execute(
                text("SELECT COUNT(*) FROM newsbot_notifications WHERE article_id=:a"),
                {"a": aid},
            ).scalar_one()
            assert cnt == 0


def test_above_threshold_sends(sample_db):
    notifier = _make_notifier(min_score=7)
    with patch("bist_bot.newsbot.notifier.send_telegram_with_retry", return_value=True) as mock_send:
        with sample_db.begin() as sess:
            sid = sess.execute(text("SELECT id FROM newsbot_sources WHERE name='test_src'")).scalar_one()
            aid = _insert_article(sess, sid, "THYAO yeni uçak siparişi")
            result = notifier.notify(
                sess,
                article_id=aid,
                title="THYAO yeni uçak siparişi",
                layer="stock",
                score=7,
                direction="positive",
                source_name="test_src",
                matched_keywords={"positive": ["yeni sözleşme"], "negative": []},
            )
            assert result is True
            assert mock_send.call_count == 1
            captured = mock_send.call_args.kwargs["text"]
            assert "📈" in captured
            assert "THYAO" in captured
            # DB record has status=sent
            status = sess.execute(
                text("SELECT status FROM newsbot_notifications WHERE article_id=:a"),
                {"a": aid},
            ).scalar_one()
            assert status == "sent"


def test_disabled_notifier_sends_nothing():
    notifier = NewsbotNotifier(token="", chat_id="", min_score=7)
    assert not notifier.enabled
    with patch("bist_bot.newsbot.notifier.send_telegram_with_retry") as mock_send:
        result = notifier.notify(
            None,  # session not used when disabled
            article_id=1,
            title="Test",
            layer="stock",
            score=9,
            direction="positive",
            source_name="test",
        )
        assert result is False
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — DB persistence
# ---------------------------------------------------------------------------


def test_notification_record_structure(sample_db):
    notifier = _make_notifier(min_score=1)
    with patch("bist_bot.newsbot.notifier.send_telegram_with_retry", return_value=True):
        with sample_db.begin() as sess:
            sid = sess.execute(text("SELECT id FROM newsbot_sources WHERE name='test_src'")).scalar_one()
            aid = _insert_article(sess, sid, "Test başlık")
            notifier.notify(
                sess,
                article_id=aid,
                title="Test başlık",
                layer="macro",
                score=8,
                direction="positive",
                source_name="test_src",
                matched_keywords={"positive": ["faiz indirimi"], "negative": []},
            )
            row = sess.execute(
                text(
                    "SELECT article_id, layer, telegram_chat_id, payload_json, status "
                    "FROM newsbot_notifications WHERE article_id=:a"
                ),
                {"a": aid},
            ).fetchone()
            assert row is not None
            assert row.article_id == aid
            assert row.layer == "macro"
            assert row.telegram_chat_id == "mock-chat"
            assert row.status == "sent"
            payload = json.loads(row.payload_json)
            assert payload["layer"] == "macro"
            assert payload["score"] == 8
