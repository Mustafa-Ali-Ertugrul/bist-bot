"""Fiyat snapshot tahmin değerlendirmesi (feedback loop).

``t0`` snapshot'ı olan her makale için vadesi gelen ``1h``/``4h``/``1d``
fiyatlarını ``newsbot_price_snapshots`` tablosuna ekler; ``1d`` horizonu
tamamlanınca haber skoru (``newsbot_layer_scores``) ile gerçekleşen fiyat
hareketini karşılaştırıp ``newsbot_feedback_log`` satırı yazar.

Metrik (basit, kasıtlı):
  - ``actual_direction``: gerçekleşen % değişim ±0.5 bant dışına taştıysa
    positive/negative, aksi halde neutral
  - ``actual_score``: % değişim 1-10 skalasına map (5 = nötr)
  - ``error_value``: |predicted_score - actual_score|
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bist_bot.app_logging import get_logger
from bist_bot.newsbot.models import NewsbotPriceSnapshot
from bist_bot.newsbot.price_snapshot import normalize_ticker

logger = get_logger("newsbot.feedback", component="newsbot.feedback")

FEEDBACK_TYPE = "price_1d"
ACTUAL_BAND_PCT = 0.5
HORIZON_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
_FOLLOWUP_HORIZONS = ("1h", "4h", "1d")


def pct_to_direction(pct: float) -> str:
    if pct > ACTUAL_BAND_PCT:
        return "positive"
    if pct < -ACTUAL_BAND_PCT:
        return "negative"
    return "neutral"


def pct_to_score(pct: float) -> int:
    """Gerçekleşen % değişimi 1-10 skoruna map eder (5 nötr, 10 = +%4+, 1 = -%4-)."""
    if pct >= 4.0:
        return 10
    if pct >= 2.0:
        return 8
    if pct > ACTUAL_BAND_PCT:
        return 7
    if pct >= -ACTUAL_BAND_PCT:
        return 5
    if pct > -2.0:
        return 4
    if pct > -4.0:
        return 2
    return 1


def _as_utc(value: datetime | None) -> datetime:
    """SQLite'ın naive datetime'ını UTC-aware yapar."""
    if value is None:
        return datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _fetch_price(service, symbol: str):
    return service.fetch_price_fn(service.provider, normalize_ticker(symbol))


def _prediction_for(session: Session, article_id: int, symbol_id: int):
    return (
        session.execute(
            select(
                text("score_1_10"),
                text("direction"),
                text("impact_level"),
            )
            .select_from(text("newsbot_layer_scores"))
            .where(
                text("article_id = :a AND symbol_id = :s AND direction IS NOT NULL"),
            )
            .params(a=article_id, s=symbol_id)
            .order_by(text("id DESC"))
            .limit(1)
        )
        .mappings()
        .first()
    )


def _write_feedback(
    session: Session,
    t0: NewsbotPriceSnapshot,
    symbol: str,
    price_later: float,
) -> bool:
    """1d fiyatı tamamlanan makale için feedback_log satırı yazar."""
    prediction = _prediction_for(session, t0.article_id, t0.symbol_id)
    if prediction is None:
        logger.warning(
            "feedback_no_prediction",
            article_id=t0.article_id,
            symbol_id=t0.symbol_id,
        )
        return False

    pct = (price_later - t0.price) / t0.price * 100.0
    actual_direction = pct_to_direction(pct)
    actual_score = pct_to_score(pct)
    error_value = abs(int(prediction["score_1_10"] or 5) - actual_score)

    session.execute(
        text(
            """
            INSERT INTO newsbot_feedback_log
                (article_id, symbol_id, predicted_direction, predicted_score,
                 predicted_impact, actual_direction, actual_score, actual_impact,
                 error_value, feedback_type)
            VALUES (:a, :s, :pred_dir, :pred_score, :pred_impact,
                    :act_dir, :act_score, :act_impact, :error, :ftype)
            """
        ),
        {
            "a": t0.article_id,
            "s": t0.symbol_id,
            "pred_dir": prediction["direction"],
            "pred_score": int(prediction["score_1_10"] or 5),
            "pred_impact": prediction["impact_level"],
            "act_dir": actual_direction,
            "act_score": actual_score,
            "act_impact": "high" if abs(pct) >= 4.0 else ("medium" if abs(pct) >= 2.0 else "low"),
            "error": round(error_value, 2),
            "ftype": FEEDBACK_TYPE,
        },
    )
    logger.info(
        "feedback_evaluated",
        article_id=t0.article_id,
        symbol_id=t0.symbol_id,
        symbol=symbol,
        pct=round(pct, 2),
        predicted_direction=prediction["direction"],
        predicted_score=int(prediction["score_1_10"] or 5),
        actual_direction=actual_direction,
        actual_score=actual_score,
        error_value=round(error_value, 2),
    )
    return True


def evaluate_due_feedback(session: Session, service, now: datetime | None = None) -> int:
    """Vadesi gelen 1h/4h/1d snapshotlarını kapatır; dönen: yazılan feedback sayısı."""
    now = now or datetime.now(UTC)
    t0_rows = (
        session.execute(
            select(NewsbotPriceSnapshot).where(NewsbotPriceSnapshot.horizon == "t0")
        )
        .scalars()
        .all()
    )
    evaluated = 0
    for t0 in t0_rows:
        captured_at = _as_utc(t0.captured_at)
        symbol = _symbol_for(session, t0.symbol_id)
        if symbol is None:
            continue

        for horizon in _FOLLOWUP_HORIZONS:
            if (now - captured_at).total_seconds() < HORIZON_SECONDS[horizon]:
                break
            exists = (
                session.execute(
                    select(NewsbotPriceSnapshot.id).where(
                        NewsbotPriceSnapshot.article_id == t0.article_id,
                        NewsbotPriceSnapshot.symbol_id == t0.symbol_id,
                        NewsbotPriceSnapshot.horizon == horizon,
                    )
                ).scalar_one_or_none()
            )
            if exists is not None:
                continue

            price = _fetch_price(service, symbol)
            if price is None:
                logger.warning(
                    "followup_snapshot_failed",
                    article_id=t0.article_id,
                    symbol=symbol,
                    horizon=horizon,
                )
                break

            session.add(
                NewsbotPriceSnapshot(
                    article_id=t0.article_id,
                    symbol_id=t0.symbol_id,
                    horizon=horizon,
                    price=price,
                )
            )
            logger.info(
                "price_snapshot_captured",
                article_id=t0.article_id,
                symbol_id=t0.symbol_id,
                symbol=symbol,
                horizon=horizon,
                price=price,
            )
            if horizon == "1d" and _write_feedback(session, t0, symbol, price):
                evaluated += 1
    return evaluated


def _symbol_for(session: Session, symbol_id: int) -> str | None:
    row = session.execute(
        select(text("symbol")).select_from(text("newsbot_symbols")).where(text("id = :s")).params(s=symbol_id)
    ).scalar_one_or_none()
    return row if row else None