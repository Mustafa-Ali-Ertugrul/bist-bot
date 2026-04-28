from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select

from bist_bot.db.database import DatabaseManager, ScanLogRecord, SignalRecord
from bist_bot.strategy.signal_models import Signal


def _serialize_reasons(reasons: list[str]) -> str:
    return json.dumps(reasons, ensure_ascii=False)


def _deserialize_reasons(raw: str | None) -> list[str]:
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
    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    def save_signal(self, signal: Signal) -> None:
        created_at = signal.timestamp

        def _write(session):
            existing = session.scalar(
                select(SignalRecord)
                .where(
                    SignalRecord.ticker == signal.ticker,
                    SignalRecord.signal_type == signal.signal_type.value,
                    SignalRecord.timestamp == created_at,
                )
                .limit(1)
            )
            if existing is not None:
                return
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
                    position_size=int(signal.position_size)
                    if signal.position_size is not None
                    else None,
                    confidence=signal.confidence,
                    reasons=" | ".join(signal.reasons),
                    conditions=_serialize_reasons(signal.reasons),
                    expires_at=signal.expires_at,
                )
            )
            return None

        self.manager.run_session(_write)

    def get_signals(self, limit: int = 50, ticker: str | None = None) -> list[dict[str, Any]]:
        def _read(session):
            statement = select(SignalRecord)
            if ticker:
                statement = statement.where(SignalRecord.ticker == ticker)
            statement = statement.order_by(
                SignalRecord.timestamp.desc(), SignalRecord.id.desc()
            ).limit(limit)
            return session.scalars(statement).all()

        rows = self.manager.run_session(_read, read_only=True)
        return [self._signal_to_dict(row) for row in rows]

    def get_recent_signals(
        self, limit: int = 50, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        return self.get_signals(limit=limit, ticker=ticker)

    def get_latest_signal(self, ticker: str) -> dict[str, Any] | None:
        row = self.manager.run_session(
            lambda session: session.scalar(
                select(SignalRecord)
                .where(SignalRecord.ticker == ticker)
                .order_by(SignalRecord.timestamp.desc(), SignalRecord.id.desc())
                .limit(1)
            ),
            read_only=True,
        )
        return self._signal_to_dict(row) if row else None

    def signal_exists(
        self,
        ticker: str,
        signal_type: str | None = None,
        timestamp: str | None = None,
    ) -> bool:
        def _read(session) -> bool:
            statement = (
                select(func.count()).select_from(SignalRecord).where(SignalRecord.ticker == ticker)
            )
            if signal_type:
                statement = statement.where(SignalRecord.signal_type == signal_type)
            if timestamp:
                statement = statement.where(SignalRecord.timestamp == timestamp)
            return bool(session.scalar(statement))

        return cast(bool, self.manager.run_session(_read, read_only=True))

    def save_scan_log(self, total: int, generated: int, buys: int, sells: int) -> None:
        def _write(session):
            session.add(
                ScanLogRecord(
                    timestamp=datetime.now(UTC),
                    total_scanned=total,
                    signals_generated=generated,
                    buy_signals=buys,
                    sell_signals=sells,
                )
            )
            return None

        self.manager.run_session(_write)

    def update_outcome(self, signal_id: int, outcome: str, outcome_price: float) -> None:
        def _write(session):
            row = session.get(SignalRecord, signal_id)
            if row is None:
                return
            original_price = float(row.price)
            row.outcome = outcome
            row.outcome_price = outcome_price
            row.outcome_date = datetime.now(UTC)
            row.profit_pct = round((outcome_price - original_price) / original_price * 100, 2)
            return None

        self.manager.run_session(_write)

    def get_performance_stats(self) -> dict[str, Any]:
        def _read(session):
            total = session.scalar(select(func.count()).select_from(SignalRecord)) or 0
            completed = (
                session.scalar(
                    select(func.count())
                    .select_from(SignalRecord)
                    .where(SignalRecord.outcome != "PENDING")
                )
                or 0
            )
            profitable = (
                session.scalar(
                    select(func.count())
                    .select_from(SignalRecord)
                    .where(SignalRecord.profit_pct > 0)
                )
                or 0
            )
            avg_profit = session.scalar(
                select(func.avg(SignalRecord.profit_pct)).where(
                    SignalRecord.profit_pct.is_not(None)
                )
            )
            return total, completed, profitable, avg_profit

        total, completed, profitable, avg_profit = self.manager.run_session(_read, read_only=True)
        return {
            "total_signals": int(total),
            "completed": int(completed),
            "profitable": int(profitable),
            "win_rate": round(profitable / completed * 100, 1) if completed > 0 else 0,
            "avg_profit_pct": round(float(avg_profit), 2) if avg_profit is not None else 0,
        }

    def get_latest_scan_log(self) -> dict[str, Any] | None:
        row = self.manager.run_session(
            lambda session: session.scalar(
                select(ScanLogRecord).order_by(ScanLogRecord.timestamp.desc()).limit(1)
            ),
            read_only=True,
        )
        return self._scan_log_to_dict(row) if row else None

    def _scan_log_to_dict(self, row: ScanLogRecord) -> dict[str, Any]:
        return {
            "total_scanned": row.total_scanned or 0,
            "signals_generated": row.signals_generated or 0,
            "buy_signals": row.buy_signals or 0,
            "sell_signals": row.sell_signals or 0,
            "timestamp": row.timestamp.isoformat()
            if isinstance(row.timestamp, datetime)
            else row.timestamp,
        }

    def _signal_to_dict(self, row: SignalRecord) -> dict[str, Any]:
        expires_at_iso = None
        is_expired = False
        if row.expires_at is not None:
            expires_at_iso = (
                row.expires_at.isoformat()
                if isinstance(row.expires_at, datetime)
                else row.expires_at
            )
            now = datetime.now(UTC)
            expires = row.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            is_expired = now >= expires

        return {
            "id": row.id,
            "timestamp": row.timestamp.isoformat()
            if isinstance(row.timestamp, datetime)
            else row.timestamp,
            "created_at": row.created_at.isoformat()
            if isinstance(row.created_at, datetime)
            else row.created_at,
            "ticker": row.ticker,
            "signal_type": row.signal_type,
            "score": row.score,
            "price": row.price,
            "stop_loss": row.stop_loss,
            "target_price": row.target_price,
            "position_size": row.position_size,
            "confidence": row.confidence,
            "reasons": _deserialize_reasons(row.conditions) or _deserialize_reasons(row.reasons),
            "outcome": row.outcome,
            "outcome_price": row.outcome_price,
            "outcome_date": row.outcome_date.isoformat()
            if isinstance(row.outcome_date, datetime)
            else row.outcome_date,
            "profit_pct": row.profit_pct,
            "conditions": _deserialize_reasons(row.conditions),
            "expires_at": expires_at_iso,
            "is_expired": is_expired,
        }
