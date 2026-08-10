"""Keyword weight auto-update based on feedback loop results.

Disabled by default (`NEWSBOT_AUTO_UPDATE_WEIGHTS=false`).
When enabled, runs after each feedback cycle to adjust keyword weights
based on prediction accuracy.

Mantık:
  - error_value == 0          → doğru tahmin → weight +0.05
  - error_value 1–3           → kabul edilebilir → weight +0.02
  - error_value 4–6           → yanlış → weight -0.05
  - error_value >= 7          → çok yanlış → weight -0.10
  - Sınırlar: min 0.1, max 2.0
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings

logger = get_logger("newsbot.weight_updater", component="newsbot.weight_updater")

_STEP_CORRECT_HIGH = 0.05
_STEP_CORRECT_LOW = 0.02
_STEP_WRONG = 0.05
_STEP_VERY_WRONG = 0.10
_WEIGHT_MIN = 0.1
_WEIGHT_MAX = 2.0


def update_keyword_weights(session: Session) -> int:
    """Feedback log'daki son 24 saatlik girdilere göre keyword ağırlıklarını günceller.

    Returns:
        Güncellenen keyword sayısı.
    """
    if not getattr(settings, "NEWSBOT_AUTO_UPDATE_WEIGHTS", False):
        logger.info("weight_update_disabled", flag=False)
        return 0

    threshold = int(getattr(settings, "NEWSBOT_WEIGHT_UPDATE_THRESHOLD", 3))
    since = datetime.now(UTC) - timedelta(hours=24)
    since_iso = since.isoformat()

    rows = session.execute(
        text(
            """
            SELECT article_id, symbol_id, error_value
            FROM newsbot_feedback_log
            WHERE created_at >= :since
            ORDER BY created_at DESC
            """
        ),
        {"since": since_iso},
    ).mappings().fetchall()

    if not rows:
        logger.info("weight_update_no_feedback_in_window")
        return 0

    updates = 0
    now_iso = datetime.now(UTC).isoformat()

    for row in rows:
        article_id = row["article_id"]
        symbol_id = row["symbol_id"]
        error_value = float(row["error_value"])

        keywords_json = (
            session.execute(
                text(
                    """
                    SELECT keywords_json FROM newsbot_layer_scores
                    WHERE article_id = :a AND symbol_id = :s
                      AND keywords_json IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"a": article_id, "s": symbol_id},
            )
            .mappings()
            .first()
        )
        if keywords_json is None:
            continue
        keywords_json = keywords_json["keywords_json"]

        if not keywords_json:
            continue

        try:
            keywords = json.loads(keywords_json)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(keywords, dict) or not keywords:
            continue

        for kw, current_weight in keywords.items():
            if not isinstance(current_weight, (int, float)):
                continue

            new_weight = _compute_new_weight(float(current_weight), error_value, threshold)

            session.execute(
                text(
                    """
                    INSERT INTO newsbot_keyword_weights
                        (keyword, layer, category, polarity, base_weight,
                         current_weight, updated_at)
                    VALUES (:kw, 'stock', NULL, NULL, :bw, :nw, :t)
                    ON CONFLICT(keyword, layer, category)
                    DO UPDATE SET
                        base_weight       = excluded.base_weight,
                        current_weight    = excluded.current_weight,
                        updated_at        = excluded.updated_at
                    """
                ),
                {
                    "kw": kw,
                    "bw": round(new_weight, 3),
                    "nw": round(new_weight, 3),
                    "t": now_iso,
                },
            )
            updates += 1

    logger.info(
        "weight_update_done",
        feedback_rows=len(rows),
        keywords_updated=updates,
        threshold=threshold,
    )
    return updates


def _compute_new_weight(weight: float, error_value: float, threshold: int) -> float:
    """Hata değerine göre yeni ağırlığı hesaplar."""
    if error_value == 0:
        step = _STEP_CORRECT_HIGH
    elif error_value <= threshold:
        step = _STEP_CORRECT_LOW
    elif error_value < 7:
        step = -_STEP_WRONG
    else:
        step = -_STEP_VERY_WRONG

    new_weight = weight + step
    return max(_WEIGHT_MIN, min(_WEIGHT_MAX, new_weight))
