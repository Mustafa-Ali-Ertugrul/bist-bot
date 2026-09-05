"""Broker auto-execution helpers for actionable signals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter
from bist_bot.config.settings import settings as default_settings
from bist_bot.execution.base import OrderSide, OrderState, OrderType
from bist_bot.observability.alerts import AlertLevel, send_alert
from bist_bot.observability.logging import log_order
from bist_bot.observability.metrics import record_order
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="execution")


@dataclass(frozen=True)
class ExecutionAttempt:
    """Outcome of a single signal execution attempt."""

    ticker: str
    side: str
    accepted: bool
    order_db_id: int | None
    broker_order_id: str | None
    state: str | None
    fill_price: float | None = None
    error: str | None = None


class ExecutionService:
    def __init__(self, db, broker=None, settings: Any | None = None) -> None:
        self.db = db
        self.broker = broker
        self.settings = settings or default_settings

    def resolve_execution_quantity(self, signal: Signal) -> float | None:
        quantity = signal.position_size
        if quantity is None:
            logger.warning(
                "auto_execute_skipped", ticker=signal.ticker, error_type="missing_quantity"
            )
            return None
        if quantity <= 0:
            logger.info(
                "auto_execute_skipped", ticker=signal.ticker, error_type="non_positive_quantity"
            )
            return None

        max_warn_quantity = getattr(self.settings, "AUTO_EXECUTE_WARN_MAX_QUANTITY", 100000)
        if quantity > max_warn_quantity:
            logger.warning(
                "auto_execute_large_quantity", ticker=signal.ticker, actionable_count=quantity
            )
        return float(quantity)

    def _require_fill_before_position(self) -> bool:
        return bool(getattr(self.settings, "AGENT_REQUIRE_FILL_BEFORE_POSITION", True))

    def _is_position_ready(self, result: Any, *, require_fill: bool) -> bool:
        if not getattr(result, "accepted", False):
            return False
        state = getattr(result, "state", None)
        state_value = (
            state.value if state is not None and hasattr(state, "value") else str(state or "")
        )
        if state_value in {OrderState.REJECTED.value, OrderState.CANCELLED.value, "ERROR"}:
            return False
        if require_fill:
            return state_value == OrderState.FILLED.value
        return True

    def _authenticate(self) -> bool:
        if self.broker is None:
            return False
        try:
            authenticated = self.broker.authenticate()
        except Exception as exc:
            inc_counter("bist_auto_execute_fail_total")
            logger.warning("auto_execute_auth_failed", error_type=type(exc).__name__)
            send_alert(
                "Broker auth failed",
                f"Auto-execute auth error: {type(exc).__name__}",
                level=AlertLevel.CRITICAL,
                error=str(exc),
            )
            return False
        if not authenticated:
            inc_counter("bist_auto_execute_fail_total")
            logger.warning("auto_execute_auth_failed", error_type="broker_auth_rejected")
            send_alert(
                "Broker auth failed",
                "Auto-execute auth rejected by broker",
                level=AlertLevel.CRITICAL,
                error="broker_auth_rejected",
            )
            return False
        return True

    def execute_signal(
        self,
        signal: Signal,
        *,
        force: bool = False,
        require_fill: bool | None = None,
    ) -> ExecutionAttempt | None:
        """Submit one actionable signal. Use force=True for agent-owned entries."""
        if self.broker is None:
            return None
        if not force and not getattr(self.settings, "AUTO_EXECUTE", False):
            return None
        if signal.signal_type not in {SignalType.STRONG_BUY, SignalType.STRONG_SELL}:
            return None

        quantity = self.resolve_execution_quantity(signal)
        if quantity is None:
            return ExecutionAttempt(
                ticker=signal.ticker,
                side="",
                accepted=False,
                order_db_id=None,
                broker_order_id=None,
                state=None,
                error="invalid_quantity",
            )

        if not self._authenticate():
            return ExecutionAttempt(
                ticker=signal.ticker,
                side="",
                accepted=False,
                order_db_id=None,
                broker_order_id=None,
                state=None,
                error="broker_auth_failed",
            )

        side = OrderSide.BUY if signal.signal_type is SignalType.STRONG_BUY else OrderSide.SELL
        fill_gate = (
            self._require_fill_before_position() if require_fill is None else bool(require_fill)
        )
        logger.info(
            "auto_execute_order_created",
            ticker=signal.ticker,
            signal_type=signal.signal_type.value,
        )
        order_row = self.db.create_order(
            ticker=signal.ticker,
            side=side.value,
            quantity=quantity,
            order_type=OrderType.MARKET.value,
            price=None,
            state="CREATED",
        )
        order_db_id = (
            int(order_row["id"]) if order_row and order_row.get("id") is not None else None
        )
        signal_snapshot = json.dumps(
            {
                "stop_loss": signal.stop_loss,
                "target_price": signal.target_price,
                "signal_type": signal.signal_type.value
                if hasattr(signal.signal_type, "value")
                else str(signal.signal_type),
                "score": getattr(signal, "score", 70.0),
                "regime": getattr(signal, "regime", None),
            },
            ensure_ascii=False,
        )
        try:
            try:
                result = self.broker.place_order(
                    ticker=signal.ticker,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                    order_db_id=order_db_id,
                    signal_snapshot=signal_snapshot,
                )
            except TypeError:
                # Broker does not support intent linkage (e.g. PaperBroker / stub)
                result = self.broker.place_order(
                    ticker=signal.ticker,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                )
            state_value = (
                result.state.value if hasattr(result.state, "value") else str(result.state)
            )
            broker_order_id = result.broker_order_id or result.order_id
            if order_db_id is not None:
                self.db.update_order(
                    order_db_id,
                    state=state_value,
                    broker_order_id=broker_order_id,
                )
            position_ready = self._is_position_ready(result, require_fill=fill_gate)
            if position_ready or getattr(result, "accepted", False):
                inc_counter("bist_auto_execute_total")
            else:
                inc_counter("bist_auto_execute_fail_total")
            record_order(side.value, state_value)
            log_order(
                "order_submitted",
                ticker=signal.ticker,
                side=side.value,
                status=state_value,
                order_id=result.order_id,
                logger=logger,
            )
            logger.info(
                "auto_execute_succeeded" if position_ready else "auto_execute_not_filled",
                ticker=signal.ticker,
                signal_type=signal.signal_type.value,
                state=state_value,
            )
            fill_price = getattr(result, "average_fill_price", None)
            if fill_price is None and position_ready:
                fill_price = float(signal.price) if signal.price is not None else None
            return ExecutionAttempt(
                ticker=signal.ticker,
                side=side.value,
                accepted=position_ready,
                order_db_id=order_db_id,
                broker_order_id=str(broker_order_id) if broker_order_id else None,
                state=state_value,
                fill_price=float(fill_price) if fill_price is not None else None,
                error=None if position_ready else f"not_ready:{state_value}",
            )
        except Exception as exc:
            if order_db_id is not None:
                self.db.update_order(order_db_id, state="REJECTED")
            inc_counter("bist_auto_execute_fail_total")
            record_order(side.value, "ERROR")
            log_order(
                "order_submit_failed",
                ticker=signal.ticker,
                side=side.value,
                status="ERROR",
                error=exc,
                logger=logger,
            )
            logger.warning(
                "auto_execute_failed",
                ticker=signal.ticker,
                signal_type=signal.signal_type.value,
                error_type=type(exc).__name__,
            )
            send_alert(
                "Order submit failed",
                f"{side.value} {signal.ticker} failed: {type(exc).__name__}",
                level=AlertLevel.CRITICAL,
                ticker=signal.ticker,
                error=str(exc),
            )
            return ExecutionAttempt(
                ticker=signal.ticker,
                side=side.value,
                accepted=False,
                order_db_id=order_db_id,
                broker_order_id=None,
                state="REJECTED",
                error=type(exc).__name__,
            )

    def auto_execute_signals(self, signals: list[Signal]) -> list[ExecutionAttempt]:
        """Submit actionable signals when AUTO_EXECUTE is enabled."""
        if not getattr(self.settings, "AUTO_EXECUTE", False) or self.broker is None:
            return []

        attempts: list[ExecutionAttempt] = []
        for signal in signals:
            if signal.signal_type not in {SignalType.STRONG_BUY, SignalType.STRONG_SELL}:
                continue
            # Scanner path: count submit success without requiring FILLED (legacy).
            attempt = self.execute_signal(signal, force=True, require_fill=False)
            if attempt is not None:
                attempts.append(attempt)
        return attempts
