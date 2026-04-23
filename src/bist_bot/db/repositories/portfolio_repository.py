from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, NamedTuple, Optional

from sqlalchemy import select

from bist_bot.db.database import DatabaseManager, PaperTradeRecord


class PaperTrade(NamedTuple):
    id: int
    ticker: str
    signal_type: str
    signal_price: float
    signal_time: datetime
    stop_loss: Optional[float]
    target_price: Optional[float]
    close_price: Optional[float]
    score: Optional[int]
    regime: Optional[str]
    filled_at: Optional[float]
    outcome: str
    actual_profit_pct: Optional[float]
    exit_price: Optional[float]
    exit_date: Optional[datetime]
    close_reason: Optional[str]
    close_time: Optional[datetime]


class PortfolioRepository:
    def __init__(self, manager: Optional[DatabaseManager] = None) -> None:
        self.manager = manager or DatabaseManager()

    def add_paper_trade(
        self,
        ticker: str,
        signal_type: str,
        signal_price: float,
        signal_time: Optional[datetime] = None,
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
        score: int = 0,
        regime: str = "UNKNOWN",
    ) -> None:
        def _write(session):
            session.add(
                PaperTradeRecord(
                    ticker=ticker,
                    signal_type=signal_type,
                    signal_price=signal_price,
                    signal_time=signal_time or datetime.now(UTC),
                    stop_loss=stop_loss,
                    target_price=target_price,
                    score=score,
                    regime=regime,
                    outcome="OPEN",
                )
            )
            return None

        self.manager.run_session(_write)

    def update_paper_close(self, ticker: str, close_price: float) -> None:
        def _write(session):
            trade = session.scalar(
                select(PaperTradeRecord)
                .where(
                    PaperTradeRecord.ticker == ticker,
                    PaperTradeRecord.outcome == "OPEN",
                )
                .order_by(PaperTradeRecord.id.desc())
                .limit(1)
            )
            if trade is None:
                return
            trade.close_price = close_price
            trade.outcome = "CLOSED"
            trade.actual_profit_pct = (
                (close_price - trade.signal_price) / trade.signal_price * 100
            )
            return None

        self.manager.run_session(_write)

    def update_all_paper_close(self, prices: dict[str, float]) -> None:
        for ticker, close_price in prices.items():
            self.update_paper_close(ticker, close_price)

    def get_open_paper_trades(self) -> list[PaperTrade]:
        rows = self.manager.run_session(
            lambda session: session.scalars(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.outcome == "OPEN")
                .order_by(PaperTradeRecord.id.asc())
            ).all(),
            read_only=True,
        )
        return [
            PaperTrade(
                id=row.id,
                ticker=row.ticker,
                signal_type=row.signal_type,
                signal_price=row.signal_price,
                signal_time=row.signal_time if isinstance(row.signal_time, datetime) else datetime.now(UTC),
                stop_loss=row.stop_loss,
                target_price=row.target_price,
                close_price=row.close_price,
                score=row.score,
                regime=row.regime,
                filled_at=row.filled_at,
                outcome=row.outcome,
                actual_profit_pct=row.actual_profit_pct,
                exit_price=row.exit_price,
                exit_date=row.exit_date if isinstance(row.exit_date, datetime) else None,
                close_reason=row.close_reason,
                close_time=row.close_time if isinstance(row.close_time, datetime) else None,
            )
            for row in rows
        ]

    def get_open_paper_trade_tickers(self) -> list[str]:
        return [trade.ticker for trade in self.get_open_paper_trades()]

    def close_paper_trade(
        self,
        ticker: str,
        exit_price: float,
        close_reason: str,
        actual_profit_pct: Optional[float] = None,
    ) -> None:
        def _write(session):
            trade = session.scalar(
                select(PaperTradeRecord)
                .where(
                    PaperTradeRecord.ticker == ticker,
                    PaperTradeRecord.outcome == "OPEN",
                )
                .order_by(PaperTradeRecord.id.desc())
                .limit(1)
            )
            if trade is None:
                return
            now = datetime.now(UTC)
            trade.exit_price = exit_price
            trade.exit_date = now
            trade.close_reason = close_reason
            trade.close_time = now
            trade.outcome = "CLOSED"
            trade.actual_profit_pct = actual_profit_pct
            return None

        self.manager.run_session(_write)

    def get_paper_performance(self) -> dict[str, Any]:
        trades = self.manager.run_session(
            lambda session: session.scalars(
                select(PaperTradeRecord).where(PaperTradeRecord.outcome == "CLOSED")
            ).all(),
            read_only=True,
        )
        if not trades:
            return {}
        profitable = sum(
            1
            for trade in trades
            if trade.actual_profit_pct and trade.actual_profit_pct > 0
        )
        total = len(trades)
        profits = [
            trade.actual_profit_pct
            for trade in trades
            if trade.actual_profit_pct is not None
        ]
        avg_profit = sum(profits) / len(profits) if profits else 0
        return {
            "total_trades": total,
            "profitable": profitable,
            "win_rate": round(profitable / total * 100, 1) if total > 0 else 0,
            "avg_profit_pct": round(avg_profit, 2),
        }
