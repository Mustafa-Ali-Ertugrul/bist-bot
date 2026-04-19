from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple, Optional

from sqlalchemy import select

from db.database import DatabaseManager, PaperTradeRecord


class PaperTrade(NamedTuple):
    id: int
    ticker: str
    signal_type: str
    signal_price: float
    signal_time: str
    stop_loss: Optional[float]
    target_price: Optional[float]
    close_price: Optional[float]
    score: Optional[int]
    regime: Optional[str]
    filled_at: Optional[float]
    outcome: str
    actual_profit_pct: Optional[float]
    exit_price: Optional[float]
    exit_date: Optional[str]
    close_reason: Optional[str]
    close_time: Optional[str]


class PortfolioRepository:
    def __init__(self, manager: Optional[DatabaseManager] = None) -> None:
        self.manager = manager or DatabaseManager()

    def add_paper_trade(
        self,
        ticker: str,
        signal_type: str,
        signal_price: float,
        signal_time: Optional[str] = None,
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
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
                    stop_loss=stop_loss,
                    target_price=target_price,
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

    def get_open_paper_trades(self) -> list[PaperTrade]:
        with self.manager.session_scope() as session:
            rows = session.scalars(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.outcome == "OPEN")
                .order_by(PaperTradeRecord.id.asc())
            ).all()
        return [
            PaperTrade(
                id=row.id,
                ticker=row.ticker,
                signal_type=row.signal_type,
                signal_price=row.signal_price,
                signal_time=row.signal_time,
                stop_loss=row.stop_loss,
                target_price=row.target_price,
                close_price=row.close_price,
                score=row.score,
                regime=row.regime,
                filled_at=row.filled_at,
                outcome=row.outcome,
                actual_profit_pct=row.actual_profit_pct,
                exit_price=row.exit_price,
                exit_date=row.exit_date,
                close_reason=row.close_reason,
                close_time=row.close_time,
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
            trades = session.scalars(select(PaperTradeRecord).where(PaperTradeRecord.outcome == "CLOSED")).all()
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
