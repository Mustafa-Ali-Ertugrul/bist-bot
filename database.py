from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select

import config
from database_manager import DatabaseManager, PaperTradeRecord, ScanLogRecord, SignalRecord
from signal_models import Signal

logger = logging.getLogger(__name__)


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


class SignalDatabase:
    def __init__(
        self,
        db_path: Optional[str] = None,
        manager: Optional[DatabaseManager] = None,
    ) -> None:
        self.manager = manager or DatabaseManager(sqlite_path=db_path or config.DB_PATH)
        self.db_path = self.manager.sqlite_path
        logger.info(f"📂 Veritabanı hazır: {self.db_path}")

    def ping(self) -> bool:
        return self.manager.ping()

    def save_signal(self, signal: Signal) -> None:
        created_at = signal.timestamp.isoformat()
        reasons_json = _serialize_reasons(signal.reasons)
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
                    conditions=reasons_json,
                )
            )
        logger.info(f"  💾 Sinyal kaydedildi: {signal.ticker}")

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

    def get_latest_signal(self, ticker: str) -> Optional[dict[str, Any]]:
        with self.manager.session_scope() as session:
            row = session.scalar(
                select(SignalRecord)
                .where(SignalRecord.ticker == ticker)
                .order_by(SignalRecord.timestamp.desc(), SignalRecord.id.desc())
                .limit(1)
            )
            if row is None:
                return None
            return self._signal_to_dict(row)

    def get_recent_signals(self, limit: int = 50, ticker: Optional[str] = None) -> list[dict[str, Any]]:
        with self.manager.session_scope() as session:
            statement = select(SignalRecord)
            if ticker:
                statement = statement.where(SignalRecord.ticker == ticker)
            statement = statement.order_by(SignalRecord.timestamp.desc(), SignalRecord.id.desc()).limit(limit)
            rows = session.scalars(statement).all()
        return [self._signal_to_dict(row) for row in rows]

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
            completed = session.scalar(
                select(func.count()).select_from(SignalRecord).where(SignalRecord.outcome != "PENDING")
            ) or 0
            profitable = session.scalar(
                select(func.count()).select_from(SignalRecord).where(SignalRecord.profit_pct > 0)
            ) or 0
            avg_profit = session.scalar(select(func.avg(SignalRecord.profit_pct)).where(SignalRecord.profit_pct.is_not(None)))

        return {
            "total_signals": int(total),
            "completed": int(completed),
            "profitable": int(profitable),
            "win_rate": round(profitable / completed * 100, 1) if completed > 0 else 0,
            "avg_profit_pct": round(float(avg_profit), 2) if avg_profit is not None else 0,
        }

    def add_paper_trade(
        self,
        ticker: str,
        signal_type: str,
        signal_price: float,
        signal_time: Optional[str] = None,
        score: int = 0,
        regime: str = "UNKNOWN",
    ) -> None:
        with self.manager.session_scope() as session:
            session.add(
                PaperTradeRecord(
                    ticker=ticker,
                    signal_type=signal_type,
                    signal_price=signal_price,
                    signal_time=signal_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    score=score,
                    regime=regime,
                    outcome="OPEN",
                )
            )

    def update_paper_close(self, ticker: str, close_price: float) -> None:
        with self.manager.session_scope() as session:
            trade = session.scalar(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.ticker == ticker, PaperTradeRecord.outcome == "OPEN")
                .order_by(PaperTradeRecord.id.desc())
                .limit(1)
            )
            if trade is None:
                return
            trade.close_price = close_price
            trade.outcome = "CLOSED"
            trade.actual_profit_pct = (trade.signal_price - close_price) / trade.signal_price * 100

    def update_all_paper_close(self, prices: dict[str, float]) -> None:
        with self.manager.session_scope() as session:
            for ticker, close_price in prices.items():
                trade = session.scalar(
                    select(PaperTradeRecord)
                    .where(PaperTradeRecord.ticker == ticker, PaperTradeRecord.outcome == "OPEN")
                    .order_by(PaperTradeRecord.id.desc())
                    .limit(1)
                )
                if trade is None:
                    continue
                trade.close_price = close_price
                trade.outcome = "CLOSED"
                trade.actual_profit_pct = (trade.signal_price - close_price) / trade.signal_price * 100

    def get_open_paper_trades(self) -> list[tuple[Any, ...]]:
        with self.manager.session_scope() as session:
            rows = session.scalars(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.outcome == "OPEN")
                .order_by(PaperTradeRecord.id.asc())
            ).all()
        return [
            (
                row.id,
                row.ticker,
                row.signal_type,
                row.signal_price,
                row.signal_time,
                row.close_price,
                row.score,
                row.regime,
                row.filled_at,
                row.outcome,
                row.actual_profit_pct,
                row.exit_price,
                row.exit_date,
            )
            for row in rows
        ]

    def close_paper_trade(
        self,
        ticker: str,
        exit_price: float,
        exit_date: str,
        actual_profit_pct: Optional[float] = None,
    ) -> None:
        with self.manager.session_scope() as session:
            trade = session.scalar(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.ticker == ticker, PaperTradeRecord.outcome == "OPEN")
                .order_by(PaperTradeRecord.id.desc())
                .limit(1)
            )
            if trade is None:
                return
            trade.exit_price = exit_price
            trade.exit_date = exit_date
            trade.outcome = "CLOSED"
            trade.actual_profit_pct = actual_profit_pct

    def get_paper_performance(self) -> dict[str, Any]:
        with self.manager.session_scope() as session:
            trades = session.scalars(
                select(PaperTradeRecord).where(PaperTradeRecord.outcome == "CLOSED")
            ).all()
        if not trades:
            return {}

        profitable = sum(1 for trade in trades if trade.actual_profit_pct and trade.actual_profit_pct > 0)
        total = len(trades)
        profits = [trade.actual_profit_pct for trade in trades if trade.actual_profit_pct is not None]
        avg_profit = sum(profits) / len(profits) if profits else 0
        return {
            "total_trades": total,
            "profitable": profitable,
            "win_rate": round(profitable / total * 100, 1) if total > 0 else 0,
            "avg_profit_pct": round(avg_profit, 2),
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
