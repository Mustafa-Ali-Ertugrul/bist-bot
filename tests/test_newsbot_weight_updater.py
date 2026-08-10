"""Keyword weight auto-update testleri (Adım 8)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from bist_bot.newsbot.schema import init_newsbot_schema
from bist_bot.newsbot.weight_updater import (
    _STEP_CORRECT_HIGH,
    _STEP_CORRECT_LOW,
    _STEP_VERY_WRONG,
    _STEP_WRONG,
    _WEIGHT_MIN,
    _WEIGHT_MAX,
    update_keyword_weights,
)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    init_newsbot_schema(eng)
    return eng


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.close()


def _insert_source(session) -> int:
    row = session.execute(
        text("INSERT INTO newsbot_sources (name, url) VALUES (:n, :u)"),
        {"n": "test_source", "u": "https://example.com"},
    )
    return row.lastrowid


def _insert_article(session, title="Test haber", content="İçerik") -> int:
    sid = _insert_source(session)
    row = session.execute(
        text("INSERT INTO newsbot_articles (source_id, title, content) VALUES (:s, :t, :c)"),
        {"s": sid, "t": title, "c": content},
    )
    return row.lastrowid


def _insert_symbol(session, symbol: str) -> int:
    row = session.execute(
        text("INSERT INTO newsbot_symbols (symbol) VALUES (:s)"),
        {"s": symbol},
    )
    return row.lastrowid


def _insert_layer_score(session, article_id: int, symbol_id: int, keywords: dict) -> int:
    row = session.execute(
        text(
            """
            INSERT INTO newsbot_layer_scores
                (article_id, symbol_id, layer, direction, score_1_10, impact_level, confidence, keywords_json)
            VALUES (:a, :s, 'stock', :dir, :score, 'low', 80, :kw)
            """
        ),
        {
            "a": article_id,
            "s": symbol_id,
            "dir": "positive",
            "score": 7,
            "kw": json.dumps(keywords),
        },
    )
    return row.lastrowid


def _insert_feedback(
    session,
    article_id: int,
    symbol_id: int,
    error_value: float,
):
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    session.execute(
        text(
            """
            INSERT INTO newsbot_feedback_log
                (article_id, symbol_id, predicted_direction, predicted_score,
                 predicted_impact, actual_direction, actual_score, actual_impact,
                 error_value, feedback_type, created_at)
            VALUES (:a, :s, :pred_dir, :pred_score, 'low', :act_dir, :act_score,
                    'low', :err, 'price_1d', :t)
            """
        ),
        {
            "a": article_id,
            "s": symbol_id,
            "pred_dir": "positive",
            "pred_score": 7,
            "act_dir": "positive",
            "act_score": 7,
            "err": error_value,
            "t": now_iso,
        },
    )


class TestWeightUpdaterDisabled:
    def test_disabled_flag_skips_update(self, session, monkeypatch):
        """flag=false iken fonksiyon 0 dönmeli."""
        monkeypatch.setattr(
            "bist_bot.newsbot.weight_updater.settings",
            type("FakeSettings", (), {"NEWSBOT_AUTO_UPDATE_WEIGHTS": False})(),
        )
        n = update_keyword_weights(session)
        assert n == 0


class TestWeightUpdateLogic:
    def test_correct_prediction_increases_weight(self, session):
        """error=0 → weight +0.05."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        _insert_layer_score(session, aid, sid, {"güçlendi": 1.0})
        _insert_feedback(session, aid, sid, error_value=0.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            n = update_keyword_weights(session)

        assert n == 1
        row = session.execute(
            text("SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='güçlendi'")
        ).mappings().one_or_none()
        assert row is not None
        assert abs(row["current_weight"] - (1.0 + _STEP_CORRECT_HIGH)) < 0.001

    def test_acceptable_prediction_slight_increase(self, session):
        """error=2 (<=threshold) → weight +0.02."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        _insert_layer_score(session, aid, sid, {"yükseldi": 1.0})
        _insert_feedback(session, aid, sid, error_value=2.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            update_keyword_weights(session)

        row = session.execute(
            text("SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='yükseldi'")
        ).mappings().one_or_none()
        assert row is not None
        assert abs(row["current_weight"] - (1.0 + _STEP_CORRECT_LOW)) < 0.001

    def test_wrong_prediction_decreases_weight(self, session):
        """error=5 (>3, <7) → weight -0.05."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        _insert_layer_score(session, aid, sid, {"düşti": 1.0})
        _insert_feedback(session, aid, sid, error_value=5.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            update_keyword_weights(session)

        row = session.execute(
            text("SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='düşti'")
        ).mappings().one_or_none()
        assert row is not None
        assert abs(row["current_weight"] - (1.0 - _STEP_WRONG)) < 0.001

    def test_very_wrong_prediction_decreases_more(self, session):
        """error=8 (>=7) → weight -0.10."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        _insert_layer_score(session, aid, sid, {"kayıp": 1.0})
        _insert_feedback(session, aid, sid, error_value=8.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            update_keyword_weights(session)

        row = session.execute(
            text("SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='kayıp'")
        ).mappings().one_or_none()
        assert row is not None
        assert abs(row["current_weight"] - (1.0 - _STEP_VERY_WRONG)) < 0.001

    def test_weight_respects_min_bound(self, session):
        """Mevcut weight 0.12 ise ve -0.10 uygulanırsa sonuç 0.1 olmalı."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        _insert_layer_score(session, aid, sid, {"esik": 0.12})
        _insert_feedback(session, aid, sid, error_value=8.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            update_keyword_weights(session)

        row = session.execute(
            text("SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='esik'")
        ).mappings().one_or_none()
        assert row is not None
        assert abs(row["current_weight"] - _WEIGHT_MIN) < 0.001

    def test_weight_respects_max_bound(self, session):
        """Mevcut weight 1.98 ise ve +0.05 uygulanırsa sonuç 2.0 olmalı."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        _insert_layer_score(session, aid, sid, {"potansiyel": 1.98})
        _insert_feedback(session, aid, sid, error_value=0.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            update_keyword_weights(session)

        row = session.execute(
            text("SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='potansiyel'")
        ).mappings().one_or_none()
        assert row is not None
        assert abs(row["current_weight"] - _WEIGHT_MAX) < 0.001

    def test_no_feedback_rows_returns_zero(self, session, monkeypatch):
        """Feedback log boşsa 0 dönmeli."""
        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            n = update_keyword_weights(session)
        assert n == 0

    def test_no_keywords_in_layer_skip(self, session, monkeypatch):
        """keywords_json NULL ise hata vermemeli, update 0 olmalı."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        # layer_score without keywords_json
        session.execute(
            text(
                """
                INSERT INTO newsbot_layer_scores
                    (article_id, layer, direction, score_1_10, impact_level, confidence)
                VALUES (:a, 'stock', 'positive', 7, 'low', 80)
                """
            ),
            {"a": aid},
        )
        _insert_feedback(session, aid, sid, error_value=0.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            n = update_keyword_weights(session)
        assert n == 0

    def test_multiple_keywords_all_updated(self, session, monkeypatch):
        """Birden fazla keyword varsa hepsi güncellenmeli."""
        aid = _insert_article(session)
        sid = _insert_symbol(session, "TEST")
        keywords = {"güçlendi": 1.0, "kara_geçti": 0.8, "beklenti_üstü": 1.2}
        _insert_layer_score(session, aid, sid, keywords)
        _insert_feedback(session, aid, sid, error_value=0.0)

        with patch("bist_bot.newsbot.weight_updater.settings") as mock_settings:
            mock_settings.NEWSBOT_AUTO_UPDATE_WEIGHTS = True
            mock_settings.NEWSBOT_WEIGHT_UPDATE_THRESHOLD = 3
            n = update_keyword_weights(session)

        assert n == 3

        for kw in ("güçlendi", "kara_geçti", "beklenti_üstü"):
            row = session.execute(
                text(f"SELECT current_weight FROM newsbot_keyword_weights WHERE keyword='{kw}'")
            ).mappings().one_or_none()
            assert row is not None
            assert row["current_weight"] > 0.0
