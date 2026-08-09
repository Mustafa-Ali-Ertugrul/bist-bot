"""Price snapshot + feedback loop testleri (Adım 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from bist_bot.db.database import Base
from bist_bot.newsbot.feedback import (
    evaluate_due_feedback,
    pct_to_direction,
    pct_to_score,
)
from bist_bot.newsbot.models import NewsbotPriceSnapshot
from bist_bot.newsbot.price_snapshot import IST, PriceSnapshotService, is_market_open, normalize_ticker
from bist_bot.newsbot.schema import init_newsbot_schema


class FakeProvider:
    """fetch_history çağrılarını sırayla price listesinden besler."""

    def __init__(self, prices: list[float | None]) -> None:
        self.prices = list(prices)
        self.calls = 0

    def fetch_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None:
        self.calls += 1
        if not self.prices:
            return None
        price = self.prices.pop(0)
        if price is None:
            return None
        return pd.DataFrame(
            {"Close": [price]},
            index=pd.to_datetime(["2026-08-10 12:00:00"]),
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


def _seed_article_with_prediction(
    engine,
    direction: str = "positive",
    score: int = 8,
    impact: str = "medium",
) -> tuple[int, int]:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO newsbot_sources (name, url) VALUES ('test', 'http://x')"))
        source_id = conn.execute(
            text("SELECT id FROM newsbot_sources WHERE name = 'test'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO newsbot_articles (source_id, title, content, content_hash) "
                "VALUES (:s, 'THYAO kar artisi', 'icerik', 'hash1')"
            ),
            {"s": source_id},
        )
        article_id = conn.execute(
            text("SELECT id FROM newsbot_articles WHERE content_hash = 'hash1'")
        ).scalar_one()
        conn.execute(
            text("INSERT INTO newsbot_symbols (symbol, company_name) VALUES ('THYAO', 'THY')")
        )
        symbol_id = conn.execute(
            text("SELECT id FROM newsbot_symbols WHERE symbol = 'THYAO'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO newsbot_layer_scores "
                "(article_id, layer, symbol_id, scope, direction, score_1_10, impact_level, confidence, keywords_json) "
                "VALUES (:a, 'stock', :s, 'stock', :d, :sc, :i, 100, '{}')"
            ),
            {"a": article_id, "s": symbol_id, "d": direction, "sc": score, "i": impact},
        )
        return article_id, symbol_id


def _insert_t0(session, article_id: int, symbol_id: int, price: float, age_hours: float = 25.0):
    session.add(
        NewsbotPriceSnapshot(
            article_id=article_id,
            symbol_id=symbol_id,
            horizon="t0",
            price=price,
            captured_at=datetime.now(UTC) - timedelta(hours=age_hours),
        )
    )
    session.commit()


def test_normalize_ticker():
    assert normalize_ticker("thyao") == "THYAO.IS"
    assert normalize_ticker("THYAO.IS") == "THYAO.IS"
    assert normalize_ticker(" asels ") == "ASELS.IS"


def test_market_open_rules():
    monday_noon = datetime(2026, 8, 10, 12, 0, tzinfo=IST)
    assert is_market_open(monday_noon) is True
    after_close = datetime(2026, 8, 10, 18, 30, tzinfo=IST)
    assert is_market_open(after_close) is False
    saturday = datetime(2026, 8, 8, 12, 0, tzinfo=IST)
    assert is_market_open(saturday) is False


def test_pct_mapping():
    assert pct_to_direction(1.0) == "positive"
    assert pct_to_direction(-0.6) == "negative"
    assert pct_to_direction(0.4) == "neutral"
    assert pct_to_score(6.0) == 10
    assert pct_to_score(3.0) == 8
    assert pct_to_score(1.0) == 7
    assert pct_to_score(0.2) == 5
    assert pct_to_score(-3.0) == 2
    assert pct_to_score(-5.0) == 1


def test_snapshot_t0_capture_and_idempotent(engine, session, monkeypatch):
    monkeypatch.setattr(
        "bist_bot.newsbot.price_snapshot.is_market_open", lambda now=None: True
    )
    article_id, symbol_id = _seed_article_with_prediction(engine)
    service = PriceSnapshotService(provider=FakeProvider([100.0]))

    captured = service.capture_t0(session, article_id, symbol_id, "THYAO")
    assert captured is True

    rows = session.execute(select(NewsbotPriceSnapshot)).scalars().all()
    assert len(rows) == 1
    assert rows[0].horizon == "t0"
    assert rows[0].price == 100.0

    again = service.capture_t0(session, article_id, symbol_id, "THYAO")
    assert again is False
    assert len(session.execute(select(NewsbotPriceSnapshot)).scalars().all()) == 1


def test_snapshot_t0_skipped_when_market_closed(engine, session, monkeypatch):
    monkeypatch.setattr(
        "bist_bot.newsbot.price_snapshot.is_market_open", lambda now=None: False
    )
    article_id, symbol_id = _seed_article_with_prediction(engine)
    service = PriceSnapshotService(provider=FakeProvider([100.0]))

    captured = service.capture_t0(session, article_id, symbol_id, "THYAO")
    assert captured is False
    assert len(session.execute(select(NewsbotPriceSnapshot)).scalars().all()) == 0


def test_evaluate_prediction_correct(engine, session):
    """Skor 8 pozitif tahmin, +%3 gerçekleşme -> doğru yön, error 0."""
    article_id, symbol_id = _seed_article_with_prediction(
        engine, direction="positive", score=8
    )
    _insert_t0(session, article_id, symbol_id, price=100.0)
    # Sırasıyla 1h, 4h, 1d fiyatları
    service = PriceSnapshotService(provider=FakeProvider([100.0, 100.0, 103.0]))

    evaluated = evaluate_due_feedback(session, service, now=datetime.now(UTC))
    session.commit()

    assert evaluated == 1
    snapshots = session.execute(select(NewsbotPriceSnapshot)).scalars().all()
    assert {s.horizon for s in snapshots} == {"t0", "1h", "4h", "1d"}
    feedback = session.execute(text("SELECT * FROM newsbot_feedback_log")).mappings().all()
    assert len(feedback) == 1
    row = feedback[0]
    assert row["predicted_score"] == 8
    assert row["predicted_direction"] == "positive"
    assert row["actual_direction"] == "positive"
    assert row["actual_score"] == 8
    assert row["error_value"] == 0
    assert row["feedback_type"] == "price_1d"


def test_evaluate_prediction_wrong(engine, session):
    """Skor 8 pozitif tahmin, -%5 gerçekleşme -> yanlış yön, yüksek error."""
    article_id, symbol_id = _seed_article_with_prediction(
        engine, direction="positive", score=8
    )
    _insert_t0(session, article_id, symbol_id, price=100.0)
    service = PriceSnapshotService(provider=FakeProvider([100.0, 100.0, 95.0]))

    evaluated = evaluate_due_feedback(session, service, now=datetime.now(UTC))
    session.commit()

    assert evaluated == 1
    feedback = session.execute(text("SELECT * FROM newsbot_feedback_log")).mappings().all()
    assert len(feedback) == 1
    row = feedback[0]
    assert row["actual_direction"] == "negative"
    assert row["actual_score"] == 1
    assert row["error_value"] == 7


def test_evaluate_due_only_mature_snapshots(engine, session):
    """Hiçbir horizon vadesi dolmamış t0 -> hiçbir followup kapatılmaz."""
    article_id, symbol_id = _seed_article_with_prediction(engine)
    _insert_t0(session, article_id, symbol_id, price=100.0, age_hours=0.5)
    service = PriceSnapshotService(provider=FakeProvider([100.0, 100.5]))

    evaluated = evaluate_due_feedback(session, service, now=datetime.now(UTC))
    session.commit()

    assert evaluated == 0
    snapshots = session.execute(select(NewsbotPriceSnapshot)).scalars().all()
    assert [s.horizon for s in snapshots] == ["t0"]