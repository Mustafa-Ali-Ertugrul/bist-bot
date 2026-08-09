"""Structured logging helpers for live trading observability.

Wraps ``bist_bot.app_logging`` so critical events always carry a stable field
set: timestamp, level, event, ticker, order_id, error, latency_ms.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Literal

from bist_bot.app_logging import BoundLogger, get_logger

_DEFAULT_LOGGER = get_logger("bist_bot.observability", component="observability")

_STANDARD_KEYS = ("ticker", "order_id", "error", "latency_ms")


def _normalize_fields(
    *,
    ticker: str | None = None,
    order_id: str | None = None,
    error: str | Exception | None = None,
    latency_ms: float | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "ticker": ticker or "",
        "order_id": order_id or "",
        "error": "" if error is None else str(error),
        "latency_ms": 0.0 if latency_ms is None else float(latency_ms),
    }
    if extra:
        for key, value in extra.items():
            if key in fields and value in (None, ""):
                continue
            fields[key] = value
    return fields


def log_event(
    event: str,
    *,
    level: str = "info",
    ticker: str | None = None,
    order_id: str | None = None,
    error: str | Exception | None = None,
    latency_ms: float | None = None,
    logger: BoundLogger | None = None,
    **extra: Any,
) -> None:
    """Emit a structured observability event.

    ``timestamp`` is injected by ``BoundLogger``; ``level`` selects the method.
    """
    bound = logger or _DEFAULT_LOGGER
    fields = _normalize_fields(
        ticker=ticker,
        order_id=order_id,
        error=error,
        latency_ms=latency_ms,
        extra=extra,
    )
    method = getattr(bound, level.lower(), None)
    if not callable(method):
        method = bound.info
    method(event, **fields)


def log_signal(
    signal_type: str,
    *,
    ticker: str,
    score: float | None = None,
    logger: BoundLogger | None = None,
    **extra: Any,
) -> None:
    log_event(
        "signal_generated",
        level="info",
        ticker=ticker,
        logger=logger,
        signal_type=str(signal_type),
        score=score,
        **extra,
    )


def log_order(
    event: str,
    *,
    ticker: str,
    side: str | None = None,
    status: str | None = None,
    order_id: str | None = None,
    latency_ms: float | None = None,
    error: str | Exception | None = None,
    logger: BoundLogger | None = None,
    **extra: Any,
) -> None:
    log_event(
        event,
        level="warning" if error else "info",
        ticker=ticker,
        order_id=order_id,
        error=error,
        latency_ms=latency_ms,
        logger=logger,
        side=side or "",
        status=status or "",
        **extra,
    )


def log_risk_reject(
    reason: str,
    *,
    ticker: str,
    logger: BoundLogger | None = None,
    **extra: Any,
) -> None:
    log_event(
        "risk_rejected",
        level="warning",
        ticker=ticker,
        error=reason,
        logger=logger,
        reason=reason,
        **extra,
    )


def log_error(
    event: str,
    error: str | Exception,
    *,
    ticker: str | None = None,
    order_id: str | None = None,
    latency_ms: float | None = None,
    logger: BoundLogger | None = None,
    **extra: Any,
) -> None:
    log_event(
        event,
        level="error",
        ticker=ticker,
        order_id=order_id,
        error=error,
        latency_ms=latency_ms,
        logger=logger,
        **extra,
    )


class timed_event:
    """Context manager that logs an event with measured ``latency_ms``."""

    def __init__(
        self,
        event: str,
        *,
        ticker: str | None = None,
        order_id: str | None = None,
        logger: BoundLogger | None = None,
        **extra: Any,
    ) -> None:
        self.event = event
        self.ticker = ticker
        self.order_id = order_id
        self.logger = logger
        self.extra = extra
        self._started = 0.0
        self.error: Exception | None = None

    def __enter__(self) -> timed_event:
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        latency_ms = (time.perf_counter() - self._started) * 1000.0
        if exc is not None:
            self.error = exc
            log_error(
                self.event,
                exc,
                ticker=self.ticker,
                order_id=self.order_id,
                latency_ms=latency_ms,
                logger=self.logger,
                **self.extra,
            )
        else:
            log_event(
                self.event,
                ticker=self.ticker,
                order_id=self.order_id,
                latency_ms=latency_ms,
                logger=self.logger,
                **self.extra,
            )
        return False


__all__ = [
    "log_error",
    "log_event",
    "log_order",
    "log_risk_reject",
    "log_signal",
    "timed_event",
]
