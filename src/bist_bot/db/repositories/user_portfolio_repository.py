"""Persistence for user watchlists, manual portfolios and benchmark series."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select

from bist_bot.db.database import (
    DatabaseManager,
    UserPortfolioRecord,
    UserPortfolioTransactionRecord,
    UserWatchlistItemRecord,
    UserWatchlistRecord,
)


class OwnershipError(PermissionError):
    """The record does not exist for this user (rendered as 404, never 403)."""


class DuplicateError(ValueError):
    """Name or ticker already exists for this user."""


class UserPortfolioRepository:
    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    # ------------------------------------------------------------------
    # Watchlists
    # ------------------------------------------------------------------
    def list_watchlists(self, user_id: int) -> list[dict[str, Any]]:
        def _read(session):
            lists = session.scalars(
                select(UserWatchlistRecord)
                .where(UserWatchlistRecord.user_id == user_id)
                .order_by(UserWatchlistRecord.id)
            ).all()
            items = session.scalars(
                select(UserWatchlistItemRecord)
                .where(UserWatchlistItemRecord.watchlist_id.in_([row.id for row in lists] or [-1]))
                .order_by(UserWatchlistItemRecord.id)
            ).all()
            grouped: dict[int, list[str]] = {}
            for item in items:
                grouped.setdefault(item.watchlist_id, []).append(item.ticker)
            return [
                {"id": row.id, "name": row.name, "tickers": grouped.get(row.id, [])}
                for row in lists
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def create_watchlist(self, user_id: int, name: str, *, limit: int = 5) -> int:
        clean = name.strip()[:60]
        if not clean:
            raise ValueError("Liste adı boş olamaz.")

        def _write(session):
            count = session.scalar(
                select(func.count(UserWatchlistRecord.id)).where(
                    UserWatchlistRecord.user_id == user_id
                )
            )
            if int(count or 0) >= limit:
                raise ValueError(f"En fazla {limit} liste oluşturulabilir.")
            existing = session.scalar(
                select(UserWatchlistRecord).where(
                    UserWatchlistRecord.user_id == user_id,
                    UserWatchlistRecord.name == clean,
                )
            )
            if existing is not None:
                raise DuplicateError("Bu adda bir liste var.")
            record = UserWatchlistRecord(user_id=user_id, name=clean, created_at=datetime.now(UTC))
            session.add(record)
            session.flush()
            return record.id

        return int(self.manager.run_session(_write))

    def delete_watchlist(self, user_id: int, watchlist_id: int) -> None:
        def _write(session):
            row = session.scalar(
                select(UserWatchlistRecord).where(
                    UserWatchlistRecord.id == watchlist_id,
                    UserWatchlistRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Liste bulunamadı.")
            session.delete(row)

        self.manager.run_session(_write)

    def add_watchlist_item(
        self, user_id: int, watchlist_id: int, ticker: str, *, limit: int = 100
    ) -> None:
        def _write(session):
            row = session.scalar(
                select(UserWatchlistRecord).where(
                    UserWatchlistRecord.id == watchlist_id,
                    UserWatchlistRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Liste bulunamadı.")
            count = session.scalar(
                select(func.count(UserWatchlistItemRecord.id)).where(
                    UserWatchlistItemRecord.watchlist_id == watchlist_id
                )
            )
            if int(count or 0) >= limit:
                raise ValueError(f"Bir listede en fazla {limit} hisse olabilir.")
            exists = session.scalar(
                select(UserWatchlistItemRecord).where(
                    UserWatchlistItemRecord.watchlist_id == watchlist_id,
                    UserWatchlistItemRecord.ticker == ticker,
                )
            )
            if exists is not None:
                return
            session.add(
                UserWatchlistItemRecord(
                    watchlist_id=watchlist_id, ticker=ticker, added_at=datetime.now(UTC)
                )
            )

        self.manager.run_session(_write)

    def remove_watchlist_item(self, user_id: int, watchlist_id: int, ticker: str) -> None:
        def _write(session):
            row = session.scalar(
                select(UserWatchlistRecord).where(
                    UserWatchlistRecord.id == watchlist_id,
                    UserWatchlistRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Liste bulunamadı.")
            session.execute(
                delete(UserWatchlistItemRecord).where(
                    UserWatchlistItemRecord.watchlist_id == watchlist_id,
                    UserWatchlistItemRecord.ticker == ticker,
                )
            )

        self.manager.run_session(_write)

    def watchlist_tickers(self, user_id: int) -> list[str]:
        def _read(session):
            rows = session.scalars(
                select(UserWatchlistItemRecord.ticker)
                .join(
                    UserWatchlistRecord,
                    UserWatchlistRecord.id == UserWatchlistItemRecord.watchlist_id,
                )
                .where(UserWatchlistRecord.user_id == user_id)
                .distinct()
            ).all()
            return [str(row) for row in rows]

        return list(self.manager.run_session(_read, read_only=True))

    # ------------------------------------------------------------------
    # Portfolios
    # ------------------------------------------------------------------
    def list_portfolios(self, user_id: int) -> list[dict[str, Any]]:
        def _read(session):
            rows = session.scalars(
                select(UserPortfolioRecord)
                .where(UserPortfolioRecord.user_id == user_id)
                .order_by(UserPortfolioRecord.id)
            ).all()
            return [{"id": row.id, "name": row.name} for row in rows]

        return list(self.manager.run_session(_read, read_only=True))

    def create_portfolio(self, user_id: int, name: str, *, limit: int = 3) -> int:
        clean = name.strip()[:60]
        if not clean:
            raise ValueError("Portföy adı boş olamaz.")

        def _write(session):
            count = session.scalar(
                select(func.count(UserPortfolioRecord.id)).where(
                    UserPortfolioRecord.user_id == user_id
                )
            )
            if int(count or 0) >= limit:
                raise ValueError(f"En fazla {limit} portföy oluşturulabilir.")
            existing = session.scalar(
                select(UserPortfolioRecord).where(
                    UserPortfolioRecord.user_id == user_id,
                    UserPortfolioRecord.name == clean,
                )
            )
            if existing is not None:
                raise DuplicateError("Bu adda bir portföy var.")
            record = UserPortfolioRecord(user_id=user_id, name=clean, created_at=datetime.now(UTC))
            session.add(record)
            session.flush()
            return record.id

        return int(self.manager.run_session(_write))

    def delete_portfolio(self, user_id: int, portfolio_id: int) -> None:
        def _write(session):
            row = session.scalar(
                select(UserPortfolioRecord).where(
                    UserPortfolioRecord.id == portfolio_id,
                    UserPortfolioRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Portföy bulunamadı.")
            session.delete(row)

        self.manager.run_session(_write)

    def add_transaction(
        self, user_id: int, portfolio_id: int, tx: dict[str, Any], *, limit: int = 500
    ) -> int:
        def _write(session):
            row = session.scalar(
                select(UserPortfolioRecord).where(
                    UserPortfolioRecord.id == portfolio_id,
                    UserPortfolioRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Portföy bulunamadı.")
            count = session.scalar(
                select(func.count(UserPortfolioTransactionRecord.id)).where(
                    UserPortfolioTransactionRecord.portfolio_id == portfolio_id
                )
            )
            if int(count or 0) >= limit:
                raise ValueError(f"Bir portföyde en fazla {limit} işlem olabilir.")
            record = UserPortfolioTransactionRecord(
                portfolio_id=portfolio_id,
                ticker=str(tx["ticker"]),
                side=str(tx["side"]),
                trade_date=tx["trade_date"],
                quantity=float(tx["quantity"]),
                price=float(tx["price"]),
                commission_tl=float(tx.get("commission_tl") or 0.0),
                note=(str(tx["note"])[:500] if tx.get("note") else None),
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.flush()
            return record.id

        return int(self.manager.run_session(_write))

    def delete_transaction(self, user_id: int, portfolio_id: int, transaction_id: int) -> None:
        def _write(session):
            portfolio = session.scalar(
                select(UserPortfolioRecord).where(
                    UserPortfolioRecord.id == portfolio_id,
                    UserPortfolioRecord.user_id == user_id,
                )
            )
            if portfolio is None:
                raise OwnershipError("Portföy bulunamadı.")
            tx = session.scalar(
                select(UserPortfolioTransactionRecord).where(
                    UserPortfolioTransactionRecord.id == transaction_id,
                    UserPortfolioTransactionRecord.portfolio_id == portfolio_id,
                )
            )
            if tx is None:
                raise OwnershipError("İşlem bulunamadı.")
            session.delete(tx)

        self.manager.run_session(_write)

    def get_transactions(self, user_id: int, portfolio_id: int) -> list[dict[str, Any]]:
        def _read(session):
            portfolio = session.scalar(
                select(UserPortfolioRecord).where(
                    UserPortfolioRecord.id == portfolio_id,
                    UserPortfolioRecord.user_id == user_id,
                )
            )
            if portfolio is None:
                raise OwnershipError("Portföy bulunamadı.")
            rows = session.scalars(
                select(UserPortfolioTransactionRecord)
                .where(UserPortfolioTransactionRecord.portfolio_id == portfolio_id)
                .order_by(
                    UserPortfolioTransactionRecord.trade_date,
                    UserPortfolioTransactionRecord.id,
                )
            ).all()
            return [
                {
                    "id": row.id,
                    "ticker": row.ticker,
                    "side": row.side,
                    "trade_date": row.trade_date,
                    "quantity": row.quantity,
                    "price": row.price,
                    "commission_tl": row.commission_tl,
                    "note": row.note,
                }
                for row in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))
