import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings

logger = get_logger(__name__, component="audit_log")


def write_audit(
    engine: Any,
    event_type: str,
    agent_state: str,
    ticker: str | None = None,
    position_id: int | None = None,
    order_id: int | None = None,
    details: dict[str, Any] | None = None,
    trigger_source: str | None = None,
) -> None:
    if not settings.agent.AUDIT_LOG_ENABLED:
        return
    try:
        details_json = json.dumps(details or {}, ensure_ascii=False, default=str)
        now = datetime.now(UTC)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO audit_trail
                    (timestamp, event_type, ticker, position_id, order_id, agent_state, details, trigger_source, created_at)
                    VALUES (:timestamp, :event_type, :ticker, :position_id, :order_id, :agent_state, :details, :trigger_source, :created_at)"""
                ),
                {
                    "timestamp": now,
                    "event_type": event_type,
                    "ticker": ticker,
                    "position_id": position_id,
                    "order_id": order_id,
                    "agent_state": agent_state,
                    "details": details_json,
                    "trigger_source": trigger_source,
                    "created_at": now,
                },
            )
    except Exception:
        logger.exception("audit_write_failed", event_type=event_type)
