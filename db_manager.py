import json
import sqlite3
import threading
from datetime import datetime
from typing import Any

import config

_DB_LOCK = threading.RLock()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


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
    with _DB_LOCK:
        conn = _get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    conditions TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL DEFAULT '',
                    score REAL NOT NULL DEFAULT 0,
                    price REAL NOT NULL DEFAULT 0,
                    stop_loss REAL DEFAULT 0,
                    target_price REAL DEFAULT 0,
                    confidence TEXT DEFAULT 'CACHE',
                    reasons TEXT DEFAULT ''
                )
                """
            )

            existing_columns = _table_columns(conn, "signals")
            if "conditions" not in existing_columns:
                conn.execute("ALTER TABLE signals ADD COLUMN conditions TEXT NOT NULL DEFAULT '[]'")
            if "created_at" not in existing_columns:
                conn.execute("ALTER TABLE signals ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signals_created_at
                ON signals(created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signals_ticker_created_at
                ON signals(ticker, created_at DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()


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

    with _DB_LOCK:
        conn = _get_connection()
        try:
            conn.execute(
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
                    reasons
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    signal_type,
                    payload,
                    created_at,
                    created_at,
                    score,
                    price,
                    stop_loss,
                    target_price,
                    confidence,
                    reasons_text,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_recent_signals(limit: int = 50) -> list[dict]:
    with _DB_LOCK:
        conn = _get_connection()
        try:
            rows = conn.execute(
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
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

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
