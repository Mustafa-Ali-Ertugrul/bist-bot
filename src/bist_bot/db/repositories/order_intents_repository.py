from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select

from bist_bot.db.database import DatabaseManager, OrderIntentRecord

_VALID_STATUSES = frozenset({"pending", "sent", "ack", "ack_unaccounted", "unknown", "rejected"})


class OrderIntentsRepository:
    """Durable intent log used to reconcile ambiguous broker submissions."""

    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    def create(
        self,
        *,
        client_id: str,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None,
        stop_price: float | None,
        order_db_id: int | None = None,
        signal_snapshot: str | None = None,
    ) -> dict[str, Any]:
        now = self.manager.now_utc()

        def _write(session):
            row = OrderIntentRecord(
                client_id=client_id,
                active_key=ticker,
                ticker=ticker,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                stop_price=stop_price,
                order_db_id=order_db_id,
                signal_snapshot=signal_snapshot,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return self._to_dict(row)

        return cast(dict[str, Any], self.manager.run_session(_write))

    def update(
        self,
        client_id: str,
        *,
        status: str,
        broker_order_id: str | None = None,
        detail: str | None = None,
        release_lock: bool | None = None,
    ) -> dict[str, Any] | None:
        normalized = status.lower()
        if normalized not in _VALID_STATUSES:
            raise ValueError(f"Unsupported order intent status: {status}")

        def _write(session):
            row = session.execute(
                select(OrderIntentRecord).where(OrderIntentRecord.client_id == client_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = normalized
            should_release = (
                normalized in {"ack", "rejected"} if release_lock is None else release_lock
            )
            if should_release:
                row.active_key = None
            if broker_order_id is not None:
                row.broker_order_id = broker_order_id
            if detail is not None:
                row.detail = detail[:1000]
            row.updated_at = self.manager.now_utc()
            session.flush()
            return self._to_dict(row)

        return cast(dict[str, Any] | None, self.manager.run_session(_write))

    def update_conditional(
        self,
        client_id: str,
        *,
        status: str,
        expected_statuses: tuple[str, ...],
        broker_order_id: str | None = None,
        detail: str | None = None,
        release_lock: bool | None = None,
    ) -> dict[str, Any] | None:
        """Compare-and-set update: updates only if current status is in expected_statuses."""
        normalized = status.lower()
        if normalized not in _VALID_STATUSES:
            raise ValueError(f"Unsupported order intent status: {status}")
        expected = {s.lower() for s in expected_statuses}

        def _write(session):
            row = session.execute(
                select(OrderIntentRecord).where(
                    OrderIntentRecord.client_id == client_id,
                    OrderIntentRecord.status.in_(expected),
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = normalized
            should_release = (
                normalized in {"ack", "rejected"} if release_lock is None else release_lock
            )
            if should_release:
                row.active_key = None
            if broker_order_id is not None:
                row.broker_order_id = broker_order_id
            if detail is not None:
                row.detail = detail[:1000]
            row.updated_at = self.manager.now_utc()
            session.flush()
            return self._to_dict(row)

        return cast(dict[str, Any] | None, self.manager.run_session(_write))

    def get(self, client_id: str) -> dict[str, Any] | None:
        def _read(session):
            row = session.execute(
                select(OrderIntentRecord).where(OrderIntentRecord.client_id == client_id)
            ).scalar_one_or_none()
            return self._to_dict(row) if row is not None else None

        return cast(dict[str, Any] | None, self.manager.run_session(_read, read_only=True))

    def get_unresolved(self, ticker: str) -> dict[str, Any] | None:
        def _read(session):
            row = session.execute(
                select(OrderIntentRecord)
                .where(
                    OrderIntentRecord.active_key == ticker,
                )
                .order_by(OrderIntentRecord.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return self._to_dict(row) if row is not None else None

        return cast(dict[str, Any] | None, self.manager.run_session(_read, read_only=True))

    def list_reconcilable(self) -> list[dict[str, Any]]:
        def _read(session):
            rows = session.execute(
                select(OrderIntentRecord)
                .where(
                    OrderIntentRecord.active_key.is_not(None),
                    OrderIntentRecord.status.in_(("pending", "sent", "unknown")),
                )
                .order_by(OrderIntentRecord.created_at.asc())
            ).scalars()
            return [self._to_dict(row) for row in rows]

        return cast(list[dict[str, Any]], self.manager.run_session(_read, read_only=True))

    def count_unaccounted_open(self) -> int:
        """Number of ack_unaccounted intents that still hold their symbol lock."""
        from sqlalchemy import func

        def _read(session):
            return session.execute(
                select(func.count())
                .select_from(OrderIntentRecord)
                .where(
                    OrderIntentRecord.status == "ack_unaccounted",
                    OrderIntentRecord.active_key.is_not(None),
                )
            ).scalar_one()

        return int(self.manager.run_session(_read, read_only=True))

    def is_broker_order_bound(self, broker_order_id: str, *, exclude_client_id: str) -> bool:
        def _read(session):
            row_id = session.execute(
                select(OrderIntentRecord.id)
                .where(
                    OrderIntentRecord.broker_order_id == broker_order_id,
                    OrderIntentRecord.client_id != exclude_client_id,
                )
                .limit(1)
            ).scalar_one_or_none()
            return row_id is not None

        return bool(self.manager.run_session(_read, read_only=True))

    @staticmethod
    def _to_dict(row: OrderIntentRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "client_id": row.client_id,
            "active_key": row.active_key,
            "ticker": row.ticker,
            "side": row.side,
            "quantity": row.quantity,
            "order_type": row.order_type,
            "price": row.price,
            "stop_price": row.stop_price,
            "order_db_id": row.order_db_id,
            "signal_snapshot": row.signal_snapshot,
            "status": row.status,
            "broker_order_id": row.broker_order_id,
            "detail": row.detail,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
