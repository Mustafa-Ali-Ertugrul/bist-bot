"""Broker auto-execution helpers for actionable signals."""

from __future__ import annotations

import logging
from typing import Any

from bist_bot.config.settings import settings as default_settings
from bist_bot.execution.base import OrderSide, OrderType
from bist_bot.strategy.signal_models import Signal, SignalType

logger = logging.getLogger(__name__)


class ExecutionService:
    def __init__(self, db, broker=None, settings: Any | None = None) -> None:
        self.db = db
        self.broker = broker
        self.settings = settings or default_settings

    def resolve_execution_quantity(self, signal: Signal) -> float | None:
        quantity = signal.position_size
        if quantity is None:
            logger.warning("Auto execution skipped for %s: quantity is missing", signal.ticker)
            return None
        if quantity <= 0:
            logger.info("Auto execution skipped for %s: quantity=%s", signal.ticker, quantity)
            return None

        max_warn_quantity = getattr(self.settings, "AUTO_EXECUTE_WARN_MAX_QUANTITY", 100000)
        if quantity > max_warn_quantity:
            logger.warning(
                "Auto execution quantity unusually large for %s: quantity=%s threshold=%s",
                signal.ticker,
                quantity,
                max_warn_quantity,
            )
        return float(quantity)

    def auto_execute_signals(self, signals: list[Signal]) -> None:
        if not getattr(self.settings, "AUTO_EXECUTE", False) or self.broker is None:
            return

        try:
            authenticated = self.broker.authenticate()
        except Exception as exc:
            logger.warning("Broker authentication failed; auto execution skipped: %s", exc)
            return
        if not authenticated:
            logger.warning("Broker authentication failed; auto execution skipped")
            return

        for signal in signals:
            if signal.signal_type not in {SignalType.STRONG_BUY, SignalType.STRONG_SELL}:
                continue

            quantity = self.resolve_execution_quantity(signal)
            if quantity is None:
                continue

            side = OrderSide.BUY if signal.signal_type is SignalType.STRONG_BUY else OrderSide.SELL
            logger.info(
                "Creating auto-execution order for %s side=%s quantity=%s",
                signal.ticker,
                side.value,
                quantity,
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
                logger.info(
                    "Auto-execution order updated for %s side=%s quantity=%s state=%s",
                    signal.ticker,
                    side.value,
                    quantity,
                    result.state.value,
                )
            except Exception as exc:
                self.db.update_order(int(order_row["id"]), state="REJECTED")
                logger.warning(
                    "Auto execution failed for %s side=%s quantity=%s: %s",
                    signal.ticker,
                    side.value,
                    quantity,
                    exc,
                )
