"""Broker auto-execution helpers for actionable signals."""

from __future__ import annotations

from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter
from bist_bot.config.settings import settings as default_settings
from bist_bot.execution.base import OrderSide, OrderType
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="execution")


class ExecutionService:
    def __init__(self, db, broker=None, settings: Any | None = None) -> None:
        self.db = db
        self.broker = broker
        self.settings = settings or default_settings

    def resolve_execution_quantity(self, signal: Signal) -> float | None:
        quantity = signal.position_size
        if quantity is None:
            logger.warning("auto_execute_skipped", ticker=signal.ticker, error_type="missing_quantity")
            return None
        if quantity <= 0:
            logger.info("auto_execute_skipped", ticker=signal.ticker, error_type="non_positive_quantity")
            return None

        max_warn_quantity = getattr(self.settings, "AUTO_EXECUTE_WARN_MAX_QUANTITY", 100000)
        if quantity > max_warn_quantity:
            logger.warning("auto_execute_large_quantity", ticker=signal.ticker, actionable_count=quantity)
        return float(quantity)

    def auto_execute_signals(self, signals: list[Signal], auto_execute: bool | None = None) -> None:
        if auto_execute is None:
            auto_execute = getattr(self.settings, 'AUTO_EXECUTE', False)
        if not auto_execute or self.broker is None:
            return

        try:
            authenticated = self.broker.authenticate()
        except Exception as exc:
            inc_counter("bist_auto_execute_fail_total")
            logger.warning("auto_execute_auth_failed", error_type=type(exc).__name__)
            return
        if not authenticated:
            inc_counter("bist_auto_execute_fail_total")
            logger.warning("auto_execute_auth_failed", error_type="broker_auth_rejected")
            return

        for signal in signals:
            if signal.signal_type not in {SignalType.STRONG_BUY, SignalType.STRONG_SELL}:
                continue

            quantity = self.resolve_execution_quantity(signal)
            if quantity is None:
                continue

            side = OrderSide.BUY if signal.signal_type is SignalType.STRONG_BUY else OrderSide.SELL
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
            try:
                result = self.broker.place_order(
                    ticker=signal.ticker,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                )
                self.db.update_order(
                    int(order_row["id"]),
                    state=result.state.value,
                    broker_order_id=result.broker_order_id or result.order_id,
                )
                inc_counter("bist_auto_execute_total")
                logger.info("auto_execute_succeeded", ticker=signal.ticker, signal_type=signal.signal_type.value)
            except Exception as exc:
                self.db.update_order(int(order_row["id"]), state="REJECTED")
                inc_counter("bist_auto_execute_fail_total")
                logger.warning(
                    "auto_execute_failed",
                    ticker=signal.ticker,
                    signal_type=signal.signal_type.value,
                    error_type=type(exc).__name__,
                )
