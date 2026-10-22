"""Persistence for Telegram links, alerts, saved screens and digest logs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select

from bist_bot.db.database import (
    DatabaseManager,
    UserAlertRecord,
    UserDigestLogRecord,
    UserSavedScreenRecord,
    UserTelegramLinkRecord,
    UserTelegramLinkTokenRecord,
)
from bist_bot.db.repositories.user_portfolio_repository import OwnershipError


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
            record = session.get(UserTelegramLinkTokenRecord, token_hash)
            if record is None or record.used_at is not None:
                return None
            expires = record.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < moment:
                return None
            record.used_at = moment
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
