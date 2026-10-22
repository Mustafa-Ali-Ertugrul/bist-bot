"""Faz 7: legal consent records, data export and account deletion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from bist_bot.db.database import DatabaseManager
from bist_bot.legal import DOCUMENTS, document_list


def record_acceptances(manager: DatabaseManager, user_id: int, documents: list[str]) -> int:
    """Store the current version of each accepted document (idempotent)."""
    versions = [
        (DOCUMENTS[slug].slug, DOCUMENTS[slug].version) for slug in documents if slug in DOCUMENTS
    ]
    if not versions:
        return 0

    def _write(session):
        for document, version in versions:
            exists = session.execute(
                sa.text(
                    "SELECT 1 FROM legal_acceptances "
                    "WHERE user_id=:u AND document=:d AND version=:v"
                ),
                {"u": user_id, "d": document, "v": version},
            ).first()
            if exists is None:
                session.execute(
                    sa.text(
                        "INSERT INTO legal_acceptances (user_id, document, version, accepted_at) "
                        "VALUES (:u, :d, :v, :t)"
                    ),
                    {"u": user_id, "d": document, "v": version, "t": datetime.now(UTC)},
                )
        return len(versions)

    return int(manager.run_session(_write))


def acceptances(manager: DatabaseManager, user_id: int) -> list[dict[str, Any]]:
    def _read(session):
        rows = session.execute(
            sa.text(
                "SELECT document, version, accepted_at FROM legal_acceptances "
                "WHERE user_id=:u ORDER BY document"
            ),
            {"u": user_id},
        ).mappings()
        return [
            {
                "document": row["document"],
                "version": row["version"],
                "accepted_at": row["accepted_at"].isoformat()
                if hasattr(row["accepted_at"], "isoformat")
                else str(row["accepted_at"]),
            }
            for row in rows
        ]

    return list(manager.run_session(_read, read_only=True))


def export_user(manager: DatabaseManager, user_id: int) -> dict[str, Any] | None:
    """Everything we hold about the user, minus authentication secrets."""

    def _read(session):
        user = (
            session.execute(
                sa.text(
                    "SELECT id, email, role, plan, plan_expires_at, trial_ends_at, created_at "
                    "FROM users WHERE id=:u"
                ),
                {"u": user_id},
            )
            .mappings()
            .first()
        )
        if user is None:
            return None

        def rows(sql: str, **params: Any) -> list[dict[str, Any]]:
            return [
                {
                    key: (value.isoformat() if hasattr(value, "isoformat") else value)
                    for key, value in row.items()
                }
                for row in session.execute(sa.text(sql), {"u": user_id, **params}).mappings()
            ]

        watchlists = rows(
            "SELECT id, name, created_at FROM user_watchlists WHERE user_id=:u ORDER BY id"
        )
        watchlist_items = rows(
            "SELECT i.watchlist_id, i.ticker, i.added_at FROM user_watchlist_items i "
            "JOIN user_watchlists w ON w.id = i.watchlist_id WHERE w.user_id=:u ORDER BY i.id"
        )
        portfolios = rows(
            "SELECT id, name, created_at FROM user_portfolios WHERE user_id=:u ORDER BY id"
        )
        transactions = rows(
            "SELECT t.portfolio_id, t.ticker, t.side, t.trade_date, t.quantity, t.price, "
            "t.commission_tl, t.note FROM user_portfolio_transactions t "
            "JOIN user_portfolios p ON p.id = t.portfolio_id WHERE p.user_id=:u ORDER BY t.id"
        )
        alerts = rows(
            "SELECT kind, target, op, threshold, only_watchlist, enabled, created_at "
            "FROM user_alerts WHERE user_id=:u ORDER BY id"
        )
        saved_screens = rows(
            "SELECT name, payload, created_at FROM user_saved_screens WHERE user_id=:u ORDER BY id"
        )
        telegram = rows(
            "SELECT chat_id, username, linked_at FROM user_telegram_links WHERE user_id=:u"
        )
        consents = rows(
            "SELECT document, version, accepted_at FROM legal_acceptances WHERE user_id=:u"
        )

        payload = {key: value for key, value in dict(user).items() if key != "password_hash"}
        return {
            "exported_at": datetime.now(UTC).isoformat(),
            "user": payload,
            "watchlists": watchlists,
            "watchlist_items": watchlist_items,
            "portfolios": portfolios,
            "portfolio_transactions": transactions,
            "alerts": alerts,
            "saved_screens": saved_screens,
            "telegram_links": telegram,
            "legal_acceptances": consents,
            "legal_documents": document_list(),
        }

    return manager.run_session(_read, read_only=True)


def delete_user(manager: DatabaseManager, user_id: int) -> bool:
    """Hard-delete the account; personal tables cascade from users.id.

    Payment requests predate the cascade rules, so they are removed explicitly.
    """

    def _write(session):
        exists = session.execute(sa.text("SELECT 1 FROM users WHERE id=:u"), {"u": user_id}).first()
        if exists is None:
            return False
        session.execute(sa.text("DELETE FROM payment_requests WHERE user_id=:u"), {"u": user_id})
        session.execute(sa.text("DELETE FROM users WHERE id=:u"), {"u": user_id})
        return True

    return bool(manager.run_session(_write))
