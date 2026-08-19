"""Order execution after risk-approved signals."""

from __future__ import annotations

import time
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter
from bist_bot.config.settings import settings as default_settings
from bist_bot.execution.base import (
    OrderResult,
    OrderSide,
    OrderState,
    OrderType,
    coerce_order_type,
)
from bist_bot.observability.alerts import AlertLevel, send_alert
from bist_bot.observability.logging import log_order
from bist_bot.observability.metrics import observe_order_latency, record_order
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="order_executor")


class OrderExecutor:
    """Route risk-approved signals to a ``BaseExecutionProvider`` implementation.

    This is the application service between strategy/risk output and venue
    submission. It does **not** re-size positions; callers must provide a
    positive ``signal.position_size`` (or explicit ``quantity``).
    """

    def __init__(
        self,
        broker: Any,
        *,
        db: Any | None = None,
        settings: Any | None = None,
        require_auto_execute: bool = True,
    ) -> None:
        self.broker = broker
        self.db = db
        self.settings = settings or default_settings
        self.require_auto_execute = require_auto_execute

    def resolve_quantity(self, signal: Signal, quantity: float | None = None) -> float | None:
        qty = (
            float(quantity)
            if quantity is not None
            else (float(signal.position_size) if signal.position_size is not None else 0.0)
        )
        if qty <= 0:
            logger.info(
                "order_executor_skipped",
                ticker=signal.ticker,
                error_type="non_positive_quantity",
            )
            return None
        max_warn = getattr(self.settings, "AUTO_EXECUTE_WARN_MAX_QUANTITY", 100_000)
        if qty > max_warn:
            logger.warning(
                "order_executor_large_quantity",
                ticker=signal.ticker,
                quantity=qty,
            )
        return qty

    def execute_signal(
        self,
        signal: Signal,
        *,
        quantity: float | None = None,
        order_type: OrderType | str = OrderType.MARKET,
        price: float | None = None,
        force: bool = False,
    ) -> OrderResult | None:
        """Submit one risk-approved signal to the broker.

        Returns ``None`` when execution is disabled / skipped, otherwise the
        broker ``OrderResult``.
        """
        if (
            self.require_auto_execute
            and not force
            and not getattr(self.settings, "AUTO_EXECUTE", False)
        ):
            logger.debug("order_executor_disabled", ticker=signal.ticker)
            return None

        if signal.signal_type not in {
            SignalType.STRONG_BUY,
            SignalType.BUY,
            SignalType.STRONG_SELL,
            SignalType.SELL,
        }:
            logger.info(
                "order_executor_skipped",
                ticker=signal.ticker,
                signal_type=signal.signal_type.name,
                error_type="non_executable_signal",
            )
            return None

        qty = self.resolve_quantity(signal, quantity=quantity)
        if qty is None:
            return None

        side = (
            OrderSide.BUY
            if signal.signal_type in {SignalType.STRONG_BUY, SignalType.BUY}
            else OrderSide.SELL
        )
        otype = coerce_order_type(order_type)

        try:
            if not self.broker.authenticate():
                inc_counter("bist_auto_execute_fail_total")
                logger.warning("order_executor_auth_failed", ticker=signal.ticker)
                send_alert(
                    "Broker auth failed",
                    f"Authentication rejected for {signal.ticker}",
                    level=AlertLevel.CRITICAL,
                    ticker=signal.ticker,
                    error="broker_auth_rejected",
                )
                return None
        except NotImplementedError:
            raise
        except Exception as exc:
            inc_counter("bist_auto_execute_fail_total")
            logger.warning(
                "order_executor_auth_failed",
                ticker=signal.ticker,
                error_type=type(exc).__name__,
            )
            send_alert(
                "Broker auth failed",
                f"Authentication error for {signal.ticker}: {type(exc).__name__}",
                level=AlertLevel.CRITICAL,
                ticker=signal.ticker,
                error=str(exc),
            )
            return None

        order_row_id: int | None = None
        if self.db is not None and hasattr(self.db, "create_order"):
            try:
                order_row = self.db.create_order(
                    ticker=signal.ticker,
                    side=side.value,
                    quantity=qty,
                    order_type=otype.value,
                    price=price,
                    state="CREATED",
                )
                order_row_id = int(order_row["id"]) if order_row and "id" in order_row else None
            except Exception as exc:
                logger.warning(
                    "order_executor_db_create_failed",
                    ticker=signal.ticker,
                    error_type=type(exc).__name__,
                )

        started = time.perf_counter()
        try:
            # Call place_order directly (unified API from execution/ package)
            result = self.broker.place_order(
                ticker=signal.ticker,
                side=side,
                quantity=qty,
                order_type=otype,
                price=price if price is not None else getattr(signal, "price", None),
            )
        except NotImplementedError:
            if (
                order_row_id is not None
                and self.db is not None
                and hasattr(self.db, "update_order")
            ):
                self.db.update_order(order_row_id, state="REJECTED")
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            observe_order_latency(latency_ms / 1000.0)
            record_order(side.value, "ERROR")
            if (
                order_row_id is not None
                and self.db is not None
                and hasattr(self.db, "update_order")
            ):
                self.db.update_order(order_row_id, state="REJECTED")
            inc_counter("bist_auto_execute_fail_total")
            log_order(
                "order_submit_failed",
                ticker=signal.ticker,
                side=side.value,
                status="ERROR",
                latency_ms=latency_ms,
                error=exc,
                logger=logger,
            )
            logger.warning(
                "order_executor_submit_failed",
                ticker=signal.ticker,
                error_type=type(exc).__name__,
            )
            send_alert(
                "Order submit failed",
                f"{side.value} {signal.ticker} failed: {type(exc).__name__}",
                level=AlertLevel.CRITICAL,
                ticker=signal.ticker,
                error=str(exc),
            )
            return OrderResult(
                accepted=False,
                order_id="",
                state=OrderState.REJECTED,
                message=str(exc),
            )

        latency_ms = (time.perf_counter() - started) * 1000.0
        observe_order_latency(latency_ms / 1000.0)

        if order_row_id is not None and self.db is not None and hasattr(self.db, "update_order"):
            try:
                self.db.update_order(
                    order_row_id,
                    state=result.state.value,
                    broker_order_id=result.broker_order_id or result.order_id,
                )
            except Exception as exc:
                logger.warning(
                    "order_executor_db_update_failed",
                    ticker=signal.ticker,
                    error_type=type(exc).__name__,
                )

        if result.accepted:
            inc_counter("bist_auto_execute_total")
            record_order(side.value, result.state.value)
            log_order(
                "order_submitted",
                ticker=signal.ticker,
                side=side.value,
                status=result.state.value,
                order_id=result.order_id,
                latency_ms=latency_ms,
                logger=logger,
                quantity=qty,
            )
            logger.info(
                "order_executor_succeeded",
                ticker=signal.ticker,
                side=side.value,
                quantity=qty,
                order_id=result.order_id,
                state=result.state.value,
            )
        else:
            inc_counter("bist_auto_execute_fail_total")
            record_order(side.value, "REJECTED")
            log_order(
                "order_rejected",
                ticker=signal.ticker,
                side=side.value,
                status="REJECTED",
                order_id=result.order_id,
                latency_ms=latency_ms,
                error=result.message,
                logger=logger,
            )
            logger.warning(
                "order_executor_rejected",
                ticker=signal.ticker,
                message=result.message,
            )
            send_alert(
                "Order rejected",
                f"{side.value} {signal.ticker} rejected: {result.message}",
                level=AlertLevel.CRITICAL,
                ticker=signal.ticker,
                order_id=result.order_id,
                error=result.message,
            )
        return result

    def execute_signals(self, signals: list[Signal], *, force: bool = False) -> list[OrderResult]:
        results: list[OrderResult] = []
        for signal in signals:
            result = self.execute_signal(signal, force=force)
            if result is not None:
                results.append(result)
        return results


__all__ = ["OrderExecutor"]
