from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select

from db.database import DatabaseManager, ScanLogRecord, SignalRecord
from signal_models import Signal


def _serialize_reasons(reasons: list[str]) -> str:
    return json.dumps(reasons, ensure_ascii=False)


def _deserialize_reasons(raw: Optional[str]) -> list[str]:
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


class SignalsRepository:
    def __init__(self, manager: Optional[DatabaseManager] = None) -> None:
        self.manager = manager or DatabaseManager()

    def save_signal(self, signal: Signal) -> None:
        created_at = signal.timestamp.isoformat()
        with self.manager.session_scope() as session:
            session.add(
                SignalRecord(
                    timestamp=created_at,
                    created_at=created_at,
                    ticker=signal.ticker,
                    signal_type=signal.signal_type.value,
                    score=float(signal.score),
                    price=float(signal.price),
                    stop_loss=float(signal.stop_loss),
                    target_price=float(signal.target_price),
                    confidence=signal.confidence,
                    reasons=" | ".join(signal.reasons),
                    conditions=_serialize_reasons(signal.reasons),
                )
            )

    def get_signals(self, limit: int = 50, ticker: Optional[str] = None) -> list[dict[str, Any]]:
        with self.manager.session_scope() as session:
            statement = select(SignalRecord)
            if ticker:
                statement = statement.where(SignalRecord.ticker == ticker)
            statement = statement.order_by(SignalRecord.timestamp.desc(), SignalRecord.id.desc()).limit(limit)
            rows = session.scalars(statement).all()
        return [self._signal_to_dict(row) for row in rows]

    def get_recent_signals(self, limit: int = 50, ticker: Optional[str] = None) -> list[dict[str, Any]]:
        return self.get_signals(limit=limit, ticker=ticker)

    def get_latest_signal(self, ticker: str) -> Optional[dict[str, Any]]:
        with self.manager.session_scope() as session:
            row = session.scalar(
                select(SignalRecord)
                .where(SignalRecord.ticker == ticker)
                .order_by(SignalRecord.timestamp.desc(), SignalRecord.id.desc())
                .limit(1)
            )
            return self._signal_to_dict(row) if row else None

    def signal_exists(self, ticker: str, signal_type: Optional[str] = None) -> bool:
        with self.manager.session_scope() as session:
            statement = select(func.count()).select_from(SignalRecord).where(SignalRecord.ticker == ticker)
            if signal_type:
                statement = statement.where(SignalRecord.signal_type == signal_type)
            return bool(session.scalar(statement))

    def save_scan_log(self, total: int, generated: int, buys: int, sells: int) -> None:
        with self.manager.session_scope() as session:
            session.add(
                ScanLogRecord(
                    timestamp=datetime.now().isoformat(),
                    total_scanned=total,
                    signals_generated=generated,
                    buy_signals=buys,
                    sell_signals=sells,
                )
            )

    def update_outcome(self, signal_id: int, outcome: str, outcome_price: float) -> None:
        with self.manager.session_scope() as session:
            row = session.get(SignalRecord, signal_id)
            if row is None:
                return
            original_price = float(row.price)
            row.outcome = outcome
            row.outcome_price = outcome_price
            row.outcome_date = datetime.now().isoformat()
            row.profit_pct = round((outcome_price - original_price) / original_price * 100, 2)

    def get_performance_stats(self) -> dict[str, Any]:
        with self.manager.session_scope() as session:
            total = session.scalar(select(func.count()).select_from(SignalRecord)) or 0
            completed = session.scalar(select(func.count()).select_from(SignalRecord).where(SignalRecord.outcome != "PENDING")) or 0
            profitable = session.scalar(select(func.count()).select_from(SignalRecord).where(SignalRecord.profit_pct > 0)) or 0
            avg_profit = session.scalar(select(func.avg(SignalRecord.profit_pct)).where(SignalRecord.profit_pct.is_not(None)))
        return {
            "total_signals": int(total),
            "completed": int(completed),
            "profitable": int(profitable),
            "win_rate": round(profitable / completed * 100, 1) if completed > 0 else 0,
            "avg_profit_pct": round(float(avg_profit), 2) if avg_profit is not None else 0,
        }

    def _signal_to_dict(self, row: SignalRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "timestamp": row.timestamp,
            "created_at": row.created_at,
            "ticker": row.ticker,
            "signal_type": row.signal_type,
            "score": row.score,
            "price": row.price,
            "stop_loss": row.stop_loss,
            "target_price": row.target_price,
            "confidence": row.confidence,
            "reasons": _deserialize_reasons(row.conditions) or _deserialize_reasons(row.reasons),
            "outcome": row.outcome,
            "outcome_price": row.outcome_price,
            "outcome_date": row.outcome_date,
            "profit_pct": row.profit_pct,
            "conditions": _deserialize_reasons(row.conditions),
        }


_DEFAULT_REPOSITORY = SignalsRepository()


def init_db() -> None:
    _DEFAULT_REPOSITORY.manager.initialize()


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
    payload = conditions
    if isinstance(payload, str):
        reasons = [payload]
    elif payload is None:
        reasons = []
    else:
        reasons = [str(item) for item in payload]

    created_at = datetime.utcnow().isoformat(timespec="seconds")
    with _DEFAULT_REPOSITORY.manager.session_scope() as session:
        session.add(
            SignalRecord(
                ticker=ticker,
                signal_type=signal_type,
                conditions=_serialize_reasons(reasons),
                created_at=created_at,
                timestamp=created_at,
                score=score,
                price=price,
                stop_loss=stop_loss,
                target_price=target_price,
                confidence=confidence,
                reasons=" | ".join(reasons),
                outcome="PENDING",
            )
        )


def get_recent_signals(limit: int = 50) -> list[dict[str, Any]]:
    return _DEFAULT_REPOSITORY.get_signals(limit=limit)
