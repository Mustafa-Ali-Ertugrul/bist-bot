from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from database_manager import DatabaseManager

_MANAGER = DatabaseManager()


def _serialize_conditions(conditions: Any) -> str:
    if conditions is None:
        return "[]"
    if isinstance(conditions, str):
        return json.dumps([conditions], ensure_ascii=False)
    try:
        return json.dumps(conditions, ensure_ascii=False)
    except TypeError:
        return json.dumps([str(conditions)], ensure_ascii=False)


def _deserialize_conditions(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in raw.split("|") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def init_db() -> None:
    _MANAGER.initialize()


def save_signal(
    ticker: str,
    signal_type: str,
    conditions: Any,
    score: float = 0.0,
    price: float = 0.0,
    stop_loss: float = 0.0,
    target_price: float = 0.0,
    confidence: str = "CACHE",
) -> None:
    payload = _serialize_conditions(conditions)
    created_at = datetime.utcnow().isoformat(timespec="seconds")
    reasons_text = " | ".join(_deserialize_conditions(payload))
    with _MANAGER.session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO signals (
                    ticker,
                    signal_type,
                    conditions,
                    created_at,
                    timestamp,
                    score,
                    price,
                    stop_loss,
                    target_price,
                    confidence,
                    reasons,
                    outcome
                )
                VALUES (
                    :ticker,
                    :signal_type,
                    :conditions,
                    :created_at,
                    :timestamp,
                    :score,
                    :price,
                    :stop_loss,
                    :target_price,
                    :confidence,
                    :reasons,
                    'PENDING'
                )
                """
            ),
            {
                "ticker": ticker,
                "signal_type": signal_type,
                "conditions": payload,
                "created_at": created_at,
                "timestamp": created_at,
                "score": score,
                "price": price,
                "stop_loss": stop_loss,
                "target_price": target_price,
                "confidence": confidence,
                "reasons": reasons_text,
            },
        )


def get_recent_signals(limit: int = 50) -> list[dict[str, Any]]:
    with _MANAGER.session_scope() as session:
        rows = session.execute(
            text(
                """
                SELECT
                    id,
                    ticker,
                    signal_type,
                    COALESCE(NULLIF(conditions, ''), reasons, '[]') AS conditions,
                    COALESCE(NULLIF(created_at, ''), timestamp) AS created_at,
                    COALESCE(score, 0) AS score,
                    COALESCE(price, 0) AS price,
                    COALESCE(stop_loss, 0) AS stop_loss,
                    COALESCE(target_price, 0) AS target_price,
                    COALESCE(NULLIF(confidence, ''), 'CACHE') AS confidence
                FROM (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY ticker
                            ORDER BY datetime(COALESCE(NULLIF(created_at, ''), timestamp)) DESC, id DESC
                        ) AS rn
                    FROM signals
                ) latest
                WHERE rn = 1
                ORDER BY datetime(COALESCE(NULLIF(created_at, ''), timestamp)) DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()

    return [
        {
            "id": row["id"],
            "ticker": row["ticker"],
            "signal_type": row["signal_type"],
            "conditions": _deserialize_conditions(row["conditions"]),
            "created_at": row["created_at"],
            "score": row["score"],
            "price": row["price"],
            "stop_loss": row["stop_loss"],
            "target_price": row["target_price"],
            "confidence": row["confidence"],
        }
        for row in rows
    ]
