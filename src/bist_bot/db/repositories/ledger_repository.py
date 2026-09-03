"""Unified trade ledger repository — paper + shadow positions in one table."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import select

from bist_bot.db.database import DatabaseManager, TradeLedgerRecord

KIND_PAPER = "PAPER"
KIND_SHADOW = "SHADOW"

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"


class TradeLedgerEntry(NamedTuple):
    id: int
    kind: str
    ticker: str
    signal_type: str
    direction: str
    score: float | None
    regime: str | None
    entry_price: float
    entry_time: datetime
    stop_loss: float | None
    target_price: float | None
    agreement_ratio: float | None
    status: str
    exit_price: float | None
    exit_time: datetime | None
    close_reason: str | None
    gross_pnl_pct: float | None
    net_pnl_pct: float | None
    paper_trade_id: int | None
    signal_id: int | None
    source: str | None


class LedgerRepository:
    """Read/write access to the unified ``trade_ledger`` table.

    Sprint 2: paper and shadow flows dual-write here so reports get a single
    consistent source. The existing ledgers (``paper_trades`` table, shadow
    CSV) stay untouched — this table is additive.
    """

    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    def record_open(
        self,
        *,
        kind: str,
        ticker: str,
        signal_type: str,
        entry_price: float,
        entry_time: datetime | None = None,
        direction: str = "long",
        score: float | None = None,
        regime: str | None = None,
        stop_loss: float | None = None,
        target_price: float | None = None,
        agreement_ratio: float | None = None,
        paper_trade_id: int | None = None,
        signal_id: int | None = None,
        source: str = "live",
    ) -> int:
        """Insert an OPEN ledger row and return its new id."""

        def _write(session):
            record = TradeLedgerRecord(
                kind=kind,
                ticker=ticker,
                signal_type=signal_type,
                direction=direction,
                score=float(score) if score is not None else None,
                regime=regime,
                entry_price=float(entry_price),
                entry_time=entry_time or datetime.now(UTC),
                stop_loss=stop_loss,
                target_price=target_price,
                agreement_ratio=agreement_ratio,
                status=STATUS_OPEN,
                paper_trade_id=paper_trade_id,
                signal_id=signal_id,
                source=source,
            )
            session.add(record)
            session.flush()
            return record.id

        return self.manager.run_session(_write)

    def close_entry(
        self,
        kind: str,
        *,
        ticker: str | None = None,
        paper_trade_id: int | None = None,
        exit_price: float,
        exit_time: datetime | None = None,
        close_reason: str | None = None,
        gross_pnl_pct: float | None = None,
        net_pnl_pct: float | None = None,
    ) -> bool:
        """Close the matching OPEN ledger row. Returns True when a row closed.

        ``paper_trade_id`` matches PAPER rows 1:1 (same-ticker double-OPEN
        positions never mix levels/PnL — same B3 contract as
        ``PortfolioRepository.close_paper_trade``). The ``ticker`` fallback
        closes the newest OPEN row for that kind — safe for SHADOW because the
        shadow service enforces one open position per ticker.
        """
        if paper_trade_id is None and ticker is None:
            raise ValueError("close_entry requires ticker or paper_trade_id")

        def _write(session):
            stmt = select(TradeLedgerRecord).where(
                TradeLedgerRecord.kind == kind,
                TradeLedgerRecord.status == STATUS_OPEN,
            )
            if paper_trade_id is not None:
                stmt = stmt.where(TradeLedgerRecord.paper_trade_id == paper_trade_id)
            else:
                stmt = stmt.where(TradeLedgerRecord.ticker == ticker)
            record = session.scalar(stmt.order_by(TradeLedgerRecord.id.desc()).limit(1))
            if record is None:
                return False
            record.exit_price = float(exit_price)
            record.exit_time = exit_time or datetime.now(UTC)
            record.close_reason = close_reason
            record.gross_pnl_pct = gross_pnl_pct
            record.net_pnl_pct = net_pnl_pct
            record.status = STATUS_CLOSED
            return True

        return self.manager.run_session(_write)

    def get_open(self, kind: str | None = None) -> list[TradeLedgerEntry]:
        return self._query(status=STATUS_OPEN, kind=kind)

    def get_closed(
        self, kind: str | None = None, since: datetime | None = None
    ) -> list[TradeLedgerEntry]:
        entries = self._query(status=STATUS_CLOSED, kind=kind)
        if since is not None:
            entries = [
                entry
                for entry in entries
                if entry.exit_time is not None and entry.exit_time >= since
            ]
        return entries

    def _query(self, *, status: str, kind: str | None) -> list[TradeLedgerEntry]:
        def _read(session):
            stmt = select(TradeLedgerRecord).where(TradeLedgerRecord.status == status)
            if kind is not None:
                stmt = stmt.where(TradeLedgerRecord.kind == kind)
            return session.scalars(stmt.order_by(TradeLedgerRecord.id.asc())).all()

        rows = self.manager.run_session(_read, read_only=True)
        return [self._to_entry(row) for row in rows]

    @staticmethod
    def _to_entry(row: TradeLedgerRecord) -> TradeLedgerEntry:
        return TradeLedgerEntry(
            id=row.id,
            kind=row.kind,
            ticker=row.ticker,
            signal_type=row.signal_type,
            direction=row.direction,
            score=row.score,
            regime=row.regime,
            entry_price=row.entry_price,
            entry_time=row.entry_time
            if isinstance(row.entry_time, datetime)
            else datetime.now(UTC),
            stop_loss=row.stop_loss,
            target_price=row.target_price,
            agreement_ratio=row.agreement_ratio,
            status=row.status,
            exit_price=row.exit_price,
            exit_time=row.exit_time if isinstance(row.exit_time, datetime) else None,
            close_reason=row.close_reason,
            gross_pnl_pct=row.gross_pnl_pct,
            net_pnl_pct=row.net_pnl_pct,
            paper_trade_id=row.paper_trade_id,
            signal_id=row.signal_id,
            source=row.source,
        )
