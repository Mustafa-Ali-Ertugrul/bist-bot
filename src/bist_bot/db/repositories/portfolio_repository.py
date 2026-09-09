from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import case, func, select

from bist_bot.db.database import DatabaseManager, PaperTradeRecord
from bist_bot.strategy.signal_models import SignalType

VALID_DIRECTIONS = ("long", "short")


def _resolve_direction(signal_type: str, stored_direction: str | None) -> str:
    """Resolve position direction: persisted column first, signal type for legacy rows."""
    if stored_direction in VALID_DIRECTIONS:
        return stored_direction
    try:
        parsed = SignalType(signal_type)
    except ValueError:
        return "long"
    return "short" if parsed.is_sell else "long"


def _gross_profit_pct(signal_price: float, close_price: float, direction: str) -> float:
    """Direction-aware gross PnL percentage (no fees) used as a fallback."""
    if signal_price <= 0:
        return 0.0
    if direction == "short":
        return (signal_price - close_price) / signal_price * 100
    return (close_price - signal_price) / signal_price * 100


class PaperTrade(NamedTuple):
    id: int
    ticker: str
    signal_type: str
    signal_price: float
    signal_time: datetime
    stop_loss: float | None
    target_price: float | None
    close_price: float | None
    score: int | None
    regime: str | None
    filled_at: float | None
    direction: str | None
    outcome: str
    actual_profit_pct: float | None
    exit_price: float | None
    exit_date: datetime | None
    close_reason: str | None
    close_time: datetime | None


class PortfolioRepository:
    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    def add_paper_trade(
        self,
        ticker: str,
        signal_type: str,
        signal_price: float,
        signal_time: datetime | None = None,
        stop_loss: float | None = None,
        target_price: float | None = None,
        score: int = 0,
        regime: str = "UNKNOWN",
        direction: str = "long",
    ) -> int | None:
        """Insert an OPEN paper trade and return its new row id.

        Sprint 2: the returned id lets the unified trade ledger link its
        PAPER mirror row via ``paper_trade_id``.
        """
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"Invalid paper trade direction: {direction!r}")

        def _write(session):
            record = PaperTradeRecord(
                ticker=ticker,
                signal_type=signal_type,
                signal_price=signal_price,
                signal_time=signal_time or datetime.now(UTC),
                stop_loss=stop_loss,
                target_price=target_price,
                score=score,
                regime=regime,
                direction=direction,
                outcome="OPEN",
            )
            session.add(record)
            session.flush()
            return record.id

        return self.manager.run_session(_write)

    def get_open_paper_trades(self) -> list[PaperTrade]:
        rows = self.manager.run_session(
            lambda session: session.scalars(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.outcome == "OPEN")
                .order_by(PaperTradeRecord.id.asc())
            ).all(),
            read_only=True,
        )
        return [self._to_paper_trade(row) for row in rows]

    @staticmethod
    def _to_paper_trade(row: Any) -> PaperTrade:
        return PaperTrade(
            id=row.id,
            ticker=row.ticker,
            signal_type=row.signal_type,
            signal_price=row.signal_price,
            signal_time=row.signal_time
            if isinstance(row.signal_time, datetime)
            else datetime.now(UTC),
            stop_loss=row.stop_loss,
            target_price=row.target_price,
            close_price=row.close_price,
            score=row.score,
            regime=row.regime,
            filled_at=row.filled_at,
            direction=row.direction,
            outcome=row.outcome,
            actual_profit_pct=row.actual_profit_pct,
            exit_price=row.exit_price,
            exit_date=row.exit_date if isinstance(row.exit_date, datetime) else None,
            close_reason=row.close_reason,
            close_time=row.close_time if isinstance(row.close_time, datetime) else None,
        )

    def get_open_paper_trade_tickers(self) -> list[str]:
        return [trade.ticker for trade in self.get_open_paper_trades()]

    def close_paper_trade(
        self,
        ticker: str,
        exit_price: float,
        close_reason: str,
        actual_profit_pct: float | None = None,
        trade_id: int | None = None,
    ) -> None:
        """Close an open paper trade.

        ``trade_id`` (Faz 4 B3): close exactly that position. Without it the
        legacy fallback closes the newest OPEN row for the ticker — kept only
        for callers without a trade reference; same-ticker double-OPEN rows
        must go through the id path so levels and PnL never mix across
        sibling trades.
        """

        def _write(session):
            if trade_id is not None:
                trade = session.scalar(
                    select(PaperTradeRecord).where(
                        PaperTradeRecord.id == trade_id,
                        PaperTradeRecord.outcome == "OPEN",
                    )
                )
            else:
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
            direction = _resolve_direction(trade.signal_type, trade.direction)
            trade.exit_price = exit_price
            trade.exit_date = now
            trade.close_reason = close_reason
            trade.close_time = now
            trade.outcome = "CLOSED"
            if actual_profit_pct is not None:
                trade.actual_profit_pct = actual_profit_pct
            else:
                trade.actual_profit_pct = _gross_profit_pct(
                    trade.signal_price, exit_price, direction
                )
            return None

        self.manager.run_session(_write)

    def get_recent_closed_trades(self, ticker: str, days: int = 5) -> list[PaperTrade]:
        """Return closed trades for a ticker within the last N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        def _read(session):
            return session.scalars(
                select(PaperTradeRecord)
                .where(
                    PaperTradeRecord.ticker == ticker,
                    PaperTradeRecord.outcome == "CLOSED",
                    PaperTradeRecord.close_time >= cutoff,
                )
                .order_by(PaperTradeRecord.id.desc())
            ).all()

        rows = self.manager.run_session(_read, read_only=True)
        return [self._to_paper_trade(row) for row in rows]

    def get_closed_trades(self, since: datetime | None = None) -> list[PaperTrade]:
        """Return all closed paper trades, optionally only those closed at/after ``since``."""

        def _read(session):
            stmt = (
                select(PaperTradeRecord)
                .where(PaperTradeRecord.outcome == "CLOSED")
                .order_by(PaperTradeRecord.id.asc())
            )
            if since is not None:
                stmt = stmt.where(PaperTradeRecord.close_time >= since)
            return session.scalars(stmt).all()

        rows = self.manager.run_session(_read, read_only=True)
        return [self._to_paper_trade(row) for row in rows]

    def get_paper_performance(self) -> dict[str, Any]:
        def _read(session):
            return session.execute(
                select(
                    func.count(),
                    func.sum(case((PaperTradeRecord.actual_profit_pct > 0, 1), else_=0)),
                    func.avg(PaperTradeRecord.actual_profit_pct),
                )
                .select_from(PaperTradeRecord)
                .where(PaperTradeRecord.outcome == "CLOSED")
            ).one()

        total, profitable, avg_profit = self.manager.run_session(_read, read_only=True)
        if not total:
            return {}
        total = int(total or 0)
        profitable = int(profitable or 0)
        return {
            "total_trades": total,
            "profitable": profitable,
            "win_rate": round(profitable / total * 100, 1) if total > 0 else 0,
            "avg_profit_pct": round(float(avg_profit), 2) if avg_profit is not None else 0.0,
        }
