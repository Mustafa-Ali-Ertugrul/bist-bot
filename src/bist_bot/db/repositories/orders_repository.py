from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select

from bist_bot.db.database import DatabaseManager, OrderRecord


class OrdersRepository:
    def __init__(self, manager: Optional[DatabaseManager] = None) -> None:
        self.manager = manager or DatabaseManager()

    def create_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None = None,
        state: str = "CREATED",
        broker_order_id: str | None = None,
        filled_qty: float = 0.0,
        avg_fill_price: float | None = None,
    ) -> dict[str, Any]:
        now = self.manager.now_iso()

        def _write(session):
            row = OrderRecord(
                ticker=ticker,
                side=side,
                qty=quantity,
                type=order_type,
                price=price,
                state=state,
                broker_order_id=broker_order_id,
                created_at=now,
                updated_at=now,
                filled_qty=filled_qty,
                avg_fill_price=avg_fill_price,
            )
            session.add(row)
            session.flush()
            return self._to_dict(row)

        return self.manager.run_session(_write)

    def update_order(
        self,
        order_id: int,
        *,
        state: str | None = None,
        broker_order_id: str | None = None,
        filled_qty: float | None = None,
        avg_fill_price: float | None = None,
    ) -> Optional[dict[str, Any]]:
        def _write(session):
            row = session.get(OrderRecord, order_id)
            if row is None:
                return None
            if state is not None:
                row.state = state
            if broker_order_id is not None:
                row.broker_order_id = broker_order_id
            if filled_qty is not None:
                row.filled_qty = filled_qty
            if avg_fill_price is not None:
                row.avg_fill_price = avg_fill_price
            row.updated_at = self.manager.now_iso()
            session.flush()
            return self._to_dict(row)

        return self.manager.run_session(_write)

    def get_pending_orders(self) -> list[dict[str, Any]]:
        rows = self.manager.run_session(
            lambda session: session.scalars(
                select(OrderRecord)
                .where(OrderRecord.state.in_(["SENT", "PARTIAL"]))
                .order_by(OrderRecord.created_at.asc(), OrderRecord.id.asc())
            ).all(),
            read_only=True,
        )
        return [self._to_dict(row) for row in rows]

    def get_order(self, order_id: int) -> Optional[dict[str, Any]]:
        row = self.manager.run_session(
            lambda session: session.get(OrderRecord, order_id),
            read_only=True,
        )
        return self._to_dict(row) if row is not None else None

    def get_open_live_position_tickers(self) -> list[str]:
        rows = self.manager.run_session(
            lambda session: session.scalars(
                select(OrderRecord).where(OrderRecord.state.in_(["FILLED", "PARTIAL"]))
            ).all(),
            read_only=True,
        )

        net_positions: dict[str, float] = {}
        for row in rows:
            executed_qty = float(row.filled_qty or 0.0)
            if executed_qty <= 0 and row.state == "FILLED":
                executed_qty = float(row.qty)
            if executed_qty <= 0:
                continue
            signed_qty = executed_qty if row.side == "BUY" else -executed_qty
            net_positions[row.ticker] = net_positions.get(row.ticker, 0.0) + signed_qty

        return sorted(
            ticker for ticker, quantity in net_positions.items() if quantity > 0
        )

    def _to_dict(self, row: OrderRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "ticker": row.ticker,
            "side": row.side,
            "qty": row.qty,
            "type": row.type,
            "price": row.price,
            "state": row.state,
            "broker_order_id": row.broker_order_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "filled_qty": row.filled_qty,
            "avg_fill_price": row.avg_fill_price,
        }
