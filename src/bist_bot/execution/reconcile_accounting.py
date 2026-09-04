"""Reconciled order fill accounting and position integration.

Bridges reconciled AlgoLab broker fills back into the application's order ledger
and live position manager so that recovered fills do not leave untracked positions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter
from bist_bot.execution.base import OrderSide

logger = get_logger(__name__, component="reconcile_accounting")


@dataclass(frozen=True)
class AccountingOutcome:
    success: bool
    status: str  # "ack" | "ack_unaccounted" | "rejected"
    detail: str
    position_id: int | None = None


class ReconcileAccountingService:
    def __init__(self, db: Any, position_manager: Any | None = None) -> None:
        self.db = db
        self.position_manager = position_manager

    def record_fill(
        self,
        *,
        intent: dict[str, Any],
        broker_order_id: str | None,
        filled_qty: float,
        avg_fill_price: float | None,
        broker_state: str,
    ) -> AccountingOutcome:
        """Apply reconciled broker execution to the database order and position ledgers.

        Returns AccountingOutcome with status="ack" if fully accounted or
        "ack_unaccounted" if position creation/update was not possible.
        """
        client_id = str(intent.get("client_id", ""))
        ticker = str(intent.get("ticker", ""))
        side_str = str(intent.get("side", "BUY")).upper()
        order_db_id = intent.get("order_db_id")

        if filled_qty <= 0:
            return AccountingOutcome(
                success=True,
                status="rejected",
                detail=f"no filled quantity (state={broker_state})",
            )

        if avg_fill_price is None or avg_fill_price <= 0:
            inc_counter("order_intents_unaccounted_total")
            return AccountingOutcome(
                success=False,
                status="ack_unaccounted",
                detail="missing average fill price from broker history",
            )

        # Update or verify the orders row
        if order_db_id is not None:
            try:
                self.db.update_order(
                    int(order_db_id),
                    state=broker_state,
                    broker_order_id=broker_order_id,
                    filled_qty=filled_qty,
                    avg_fill_price=avg_fill_price,
                )
            except Exception:
                logger.exception("reconcile_update_order_failed", order_db_id=order_db_id)
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail=f"failed to update order {order_db_id}",
                )

        # Decode signal snapshot for position parameters
        snapshot_raw = intent.get("signal_snapshot")
        snapshot: dict[str, Any] = {}
        if snapshot_raw:
            try:
                snapshot = json.loads(str(snapshot_raw))
            except Exception:
                logger.warning("reconcile_corrupt_signal_snapshot", client_id=client_id)

        if not self.position_manager:
            inc_counter("order_intents_unaccounted_total")
            return AccountingOutcome(
                success=False,
                status="ack_unaccounted",
                detail="position manager unavailable",
            )

        # BUY path: open position
        if side_str in {"BUY", OrderSide.BUY.value}:
            if not snapshot:
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail="missing signal snapshot for BUY position parameters",
                )

            stop_loss = snapshot.get("stop_loss")
            target_price = snapshot.get("target_price")
            if not stop_loss or not target_price:
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail="signal snapshot missing stop_loss or target_price",
                )

            # Idempotency check: does position already exist for this order_db_id?
            existing_position = self.position_manager.get_position(ticker)
            if existing_position and existing_position.get("entry_order_id") == order_db_id:
                return AccountingOutcome(
                    success=True,
                    status="ack",
                    detail="position already exists for this order",
                    position_id=int(existing_position["id"]),
                )

            pos = self.position_manager.open_position(
                ticker=ticker,
                entry_order_id=int(order_db_id) if order_db_id is not None else 0,
                entry_price=float(avg_fill_price),
                quantity=float(filled_qty),
                stop_loss=float(stop_loss),
                target_price=float(target_price),
                signal_type=str(snapshot.get("signal_type", "STRONG_BUY")),
                signal_score=float(snapshot.get("score", 70.0)),
                regime=snapshot.get("regime"),
            )
            if pos is None:
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail="position_manager.open_position returned None",
                )
            return AccountingOutcome(
                success=True,
                status="ack",
                detail=f"position opened (qty={filled_qty}, price={avg_fill_price})",
                position_id=getattr(pos, "id", None),
            )

        # SELL path: close existing position.
        # No partial-reduce path exists in PositionManager, so a fill whose
        # quantity differs from the open position is fail-closed.
        if side_str in {"SELL", OrderSide.SELL.value}:
            pos = self.position_manager.get_position(ticker)
            if not pos:
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail=f"no open position found to close for ticker {ticker}",
                )

            pos_id = int(pos["id"])
            pos_qty = float(pos.get("quantity", 0.0) or 0.0)
            if abs(pos_qty - float(filled_qty)) > 1e-9:
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail=(
                        f"partial SELL exit ({filled_qty} of open {pos_qty}) has no "
                        "reduce path; manual resolution required"
                    ),
                )
            try:
                self.position_manager.close_position(
                    position_id=pos_id,
                    exit_price=float(avg_fill_price),
                    exit_reason="RECONCILED_EXIT",
                    exit_order_id=int(order_db_id) if order_db_id is not None else None,
                )
            except Exception:
                logger.exception("reconcile_close_position_failed", position_id=pos_id)
                inc_counter("order_intents_unaccounted_total")
                return AccountingOutcome(
                    success=False,
                    status="ack_unaccounted",
                    detail=f"failed to close position {pos_id}",
                )

            return AccountingOutcome(
                success=True,
                status="ack",
                detail=f"position {pos_id} closed at {avg_fill_price}",
                position_id=pos_id,
            )

        # Unknown side
        inc_counter("order_intents_unaccounted_total")
        return AccountingOutcome(
            success=False,
            status="ack_unaccounted",
            detail=f"unsupported side: {side_str}",
        )
