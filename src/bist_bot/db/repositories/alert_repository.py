"""Persistence for Telegram links, alerts, saved screens and digest logs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from bist_bot.db.database import (
    DatabaseManager,
    UserAlertEventRecord,
    UserAlertRecord,
    UserDigestLogRecord,
    UserSavedScreenRecord,
    UserTelegramLinkRecord,
    UserTelegramLinkTokenRecord,
)
from bist_bot.db.repositories.user_portfolio_repository import OwnershipError


def _is_duplicate_violation(exc: IntegrityError) -> bool:
    """True only for a unique-key race, never for a real data error."""
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "23505":  # PostgreSQL unique_violation
        return True
    text = str(orig or exc).lower()
    return "unique constraint failed" in text or "duplicate key value" in text


class AlertRepository:
    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    # ------------------------------------------------------------------
    # Link tokens + links
    # ------------------------------------------------------------------
    def create_link_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        def _write(session):
            session.add(
                UserTelegramLinkTokenRecord(
                    token_hash=token_hash,
                    user_id=user_id,
                    expires_at=expires_at,
                    created_at=datetime.now(UTC),
                )
            )

        self.manager.run_session(_write)

    def consume_link_token(self, token_hash: str, now: datetime | None = None) -> int | None:
        moment = now or datetime.now(UTC)

        def _write(session):
            # Atomic claim: only one concurrent /start can flip used_at, so a
            # single-use token can never be spent twice (TOCTOU guard). The
            # expiry check stays in Python to keep its tz normalization.
            claimed = session.execute(
                update(UserTelegramLinkTokenRecord)
                .where(
                    UserTelegramLinkTokenRecord.token_hash == token_hash,
                    UserTelegramLinkTokenRecord.used_at.is_(None),
                )
                .values(used_at=moment)
            )
            if claimed.rowcount != 1:
                return None
            record = session.get(UserTelegramLinkTokenRecord, token_hash)
            if record is None:
                return None
            expires = record.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < moment:
                return None
            return record.user_id

        return self.manager.run_session(_write)

    def get_link(self, user_id: int) -> dict[str, Any] | None:
        def _read(session):
            row = session.scalar(
                select(UserTelegramLinkRecord).where(UserTelegramLinkRecord.user_id == user_id)
            )
            if row is None:
                return None
            return {
                "user_id": row.user_id,
                "chat_id": row.chat_id,
                "username": row.username,
                "linked_at": row.linked_at.isoformat(),
            }

        return self.manager.run_session(_read, read_only=True)

    def save_link(self, user_id: int, chat_id: str, username: str | None) -> None:
        def _write(session):
            # A chat can belong to only one account.
            session.execute(
                delete(UserTelegramLinkRecord).where(UserTelegramLinkRecord.chat_id == chat_id)
            )
            row = session.scalar(
                select(UserTelegramLinkRecord).where(UserTelegramLinkRecord.user_id == user_id)
            )
            if row is None:
                session.add(
                    UserTelegramLinkRecord(
                        user_id=user_id,
                        chat_id=chat_id,
                        username=username,
                        linked_at=datetime.now(UTC),
                    )
                )
            else:
                row.chat_id = chat_id
                row.username = username
                row.linked_at = datetime.now(UTC)

        self.manager.run_session(_write)

    def delete_link(self, user_id: int) -> None:
        def _write(session):
            session.execute(
                delete(UserTelegramLinkRecord).where(UserTelegramLinkRecord.user_id == user_id)
            )

        self.manager.run_session(_write)

    def delete_link_by_chat(self, chat_id: str) -> None:
        def _write(session):
            session.execute(
                delete(UserTelegramLinkRecord).where(UserTelegramLinkRecord.chat_id == chat_id)
            )

        self.manager.run_session(_write)

    def list_links(self) -> list[dict[str, Any]]:
        def _read(session):
            rows = session.scalars(select(UserTelegramLinkRecord)).all()
            return [{"user_id": row.user_id, "chat_id": row.chat_id} for row in rows]

        return list(self.manager.run_session(_read, read_only=True))

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    def list_alerts(self, user_id: int) -> list[dict[str, Any]]:
        def _read(session):
            rows = session.scalars(
                select(UserAlertRecord)
                .where(UserAlertRecord.user_id == user_id)
                .order_by(UserAlertRecord.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "target": row.target,
                    "op": row.op,
                    "threshold": row.threshold,
                    "only_watchlist": row.only_watchlist,
                    "enabled": row.enabled,
                }
                for row in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def list_all_alerts(self) -> list[dict[str, Any]]:
        def _read(session):
            rows = session.scalars(
                select(UserAlertRecord)
                .where(UserAlertRecord.enabled.is_(True))
                .order_by(UserAlertRecord.user_id, UserAlertRecord.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "kind": row.kind,
                    "target": row.target,
                    "op": row.op,
                    "threshold": row.threshold,
                    "only_watchlist": row.only_watchlist,
                }
                for row in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def list_user_ids_with_alerts(self) -> list[int]:
        """Users who have at least one enabled alert or one saved screen."""
        def _read(session):
            alert_users = set(
                session.scalars(
                    select(UserAlertRecord.user_id).where(UserAlertRecord.enabled.is_(True))
                ).all()
            )
            screen_users = set(session.scalars(select(UserSavedScreenRecord.user_id)).all())
            return sorted({int(value) for value in alert_users | screen_users})

        return list(self.manager.run_session(_read, read_only=True))

    def add_alert(self, user_id: int, data: dict[str, Any], *, limit: int = 20) -> int:
        def _write(session):
            count = session.scalar(
                select(func.count(UserAlertRecord.id)).where(UserAlertRecord.user_id == user_id)
            )
            if int(count or 0) >= limit:
                raise ValueError(f"En fazla {limit} alarm kurulabilir.")
            record = UserAlertRecord(
                user_id=user_id,
                kind=str(data["kind"]),
                target=str(data["target"]),
                op=(str(data["op"]) if data.get("op") else None),
                threshold=(float(data["threshold"]) if data.get("threshold") is not None else None),
                only_watchlist=bool(data.get("only_watchlist")),
                enabled=True,
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.flush()
            return record.id

        return int(self.manager.run_session(_write))

    def delete_alert(self, user_id: int, alert_id: int) -> None:
        def _write(session):
            row = session.scalar(
                select(UserAlertRecord).where(
                    UserAlertRecord.id == alert_id,
                    UserAlertRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Alarm bulunamadı.")
            session.delete(row)

        self.manager.run_session(_write)

    def disable_alert(self, alert_id: int) -> None:
        def _write(session):
            row = session.get(UserAlertRecord, alert_id)
            if row is not None:
                row.enabled = False

        self.manager.run_session(_write)

    # ------------------------------------------------------------------
    # Saved screens
    # ------------------------------------------------------------------
    def list_saved_screens(self, user_id: int) -> list[dict[str, Any]]:
        def _read(session):
            rows = session.scalars(
                select(UserSavedScreenRecord)
                .where(UserSavedScreenRecord.user_id == user_id)
                .order_by(UserSavedScreenRecord.id)
            ).all()
            out = []
            for row in rows:
                try:
                    payload = json.loads(row.payload)
                except json.JSONDecodeError:
                    payload = {}
                out.append({"id": row.id, "name": row.name, "payload": payload})
            return out

        return list(self.manager.run_session(_read, read_only=True))

    def add_saved_screen(
        self, user_id: int, name: str, payload: dict[str, Any], *, limit: int = 10
    ) -> int:
        clean = name.strip()[:60]
        if not clean:
            raise ValueError("Filtre adı boş olamaz.")

        def _write(session):
            count = session.scalar(
                select(func.count(UserSavedScreenRecord.id)).where(
                    UserSavedScreenRecord.user_id == user_id
                )
            )
            if int(count or 0) >= limit:
                raise ValueError(f"En fazla {limit} filtre kaydedilebilir.")
            existing = session.scalar(
                select(UserSavedScreenRecord).where(
                    UserSavedScreenRecord.user_id == user_id,
                    UserSavedScreenRecord.name == clean,
                )
            )
            if existing is not None:
                raise ValueError("Bu adda bir filtre var.")
            record = UserSavedScreenRecord(
                user_id=user_id,
                name=clean,
                payload=json.dumps(payload, ensure_ascii=False),
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.flush()
            return record.id

        return int(self.manager.run_session(_write))

    def delete_saved_screen(self, user_id: int, screen_id: int) -> None:
        def _write(session):
            row = session.scalar(
                select(UserSavedScreenRecord).where(
                    UserSavedScreenRecord.id == screen_id,
                    UserSavedScreenRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Filtre bulunamadı.")
            session.delete(row)

        self.manager.run_session(_write)

    # ------------------------------------------------------------------
    # Digest log
    # ------------------------------------------------------------------
    def was_digest_sent(self, user_id: int, as_of: date) -> bool:
        def _read(session):
            row = session.get(UserDigestLogRecord, (user_id, as_of))
            return row is not None

        return bool(self.manager.run_session(_read, read_only=True))

    def mark_digest_sent(self, user_id: int, as_of: date) -> None:
        def _write(session):
            if session.get(UserDigestLogRecord, (user_id, as_of)) is None:
                session.add(
                    UserDigestLogRecord(user_id=user_id, as_of=as_of, sent_at=datetime.now(UTC))
                )

        self.manager.run_session(_write)

    # ------------------------------------------------------------------
    # Alert events (Faz P3.3 in-app history)
    # ------------------------------------------------------------------
    def record_events(self, user_id: int, as_of: date, events: list[dict[str, Any]]) -> int:
        """Insert one row per (user, day, ref); duplicates are ignored.

        The unique constraint is the real guard: two scheduler runs racing on the
        same day must not double-write, so each row is inserted inside its own
        savepoint and a constraint violation is swallowed instead of aborting
        the whole transaction.
        """
        if not events:
            return 0

        def _write(session):
            inserted = 0
            for item in events:
                ref = str(item["ref"])[:120]
                existing = session.scalar(
                    select(UserAlertEventRecord.id).where(
                        UserAlertEventRecord.user_id == user_id,
                        UserAlertEventRecord.as_of == as_of,
                        UserAlertEventRecord.ref == ref,
                    )
                )
                if existing is not None:
                    continue
                try:
                    with session.begin_nested():
                        session.add(
                            UserAlertEventRecord(
                                user_id=user_id,
                                as_of=as_of,
                                kind=str(item.get("kind") or "alert"),
                                ref=ref,
                                title=str(item.get("title") or "")[:200],
                                message=(
                                    str(item["message"])[:2000] if item.get("message") else None
                                ),
                                created_at=datetime.now(UTC),
                            )
                        )
                except IntegrityError as exc:
                    # Only a concurrent duplicate is expected here; anything
                    # else (NOT NULL, FK, ...) is a real bug and must surface.
                    if not _is_duplicate_violation(exc):
                        raise
                    continue
                inserted += 1
            return inserted

        return int(self.manager.run_session(_write))

    def list_events(
        self, user_id: int, *, limit: int = 50, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        def _read(session):
            stmt = select(UserAlertEventRecord).where(UserAlertEventRecord.user_id == user_id)
            if unread_only:
                stmt = stmt.where(UserAlertEventRecord.read_at.is_(None))
            rows = session.scalars(
                stmt.order_by(
                    UserAlertEventRecord.as_of.desc(), UserAlertEventRecord.id.desc()
                ).limit(max(1, min(int(limit), 200)))
            ).all()
            return [
                {
                    "id": row.id,
                    "as_of": row.as_of.isoformat(),
                    "kind": row.kind,
                    "ref": row.ref,
                    "title": row.title,
                    "message": row.message,
                    "read": row.read_at is not None,
                }
                for row in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def count_unread_events(self, user_id: int) -> int:
        def _read(session):
            return session.scalar(
                select(func.count(UserAlertEventRecord.id)).where(
                    UserAlertEventRecord.user_id == user_id,
                    UserAlertEventRecord.read_at.is_(None),
                )
            )

        return int(self.manager.run_session(_read, read_only=True) or 0)

    def mark_events_read(self, user_id: int, *, event_id: int | None = None) -> int:
        def _write(session):
            stmt = select(UserAlertEventRecord).where(
                UserAlertEventRecord.user_id == user_id,
                UserAlertEventRecord.read_at.is_(None),
            )
            if event_id is not None:
                stmt = stmt.where(UserAlertEventRecord.id == event_id)
            rows = session.scalars(stmt).all()
            now = datetime.now(UTC)
            for row in rows:
                row.read_at = now
            return len(rows)

        return int(self.manager.run_session(_write))

    def update_alert(
        self, user_id: int, alert_id: int, changes: dict[str, Any]
    ) -> dict[str, Any]:
        def _write(session):
            row = session.scalar(
                select(UserAlertRecord).where(
                    UserAlertRecord.id == alert_id,
                    UserAlertRecord.user_id == user_id,
                )
            )
            if row is None:
                raise OwnershipError("Alarm bulunamadı.")
            if "enabled" in changes:
                row.enabled = bool(changes["enabled"])
            if "threshold" in changes and changes["threshold"] is not None:
                row.threshold = float(changes["threshold"])
            if changes.get("op"):
                row.op = str(changes["op"])
            return {
                "id": row.id,
                "kind": row.kind,
                "target": row.target,
                "op": row.op,
                "threshold": row.threshold,
                "only_watchlist": row.only_watchlist,
                "enabled": row.enabled,
            }

        return dict(self.manager.run_session(_write))
