"""Minimal structured logging helpers with JSON and console renderers."""

from __future__ import annotations

import io
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

try:
    import structlog as _structlog  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    _structlog = None

from bist_bot.config.settings import settings
from bist_bot.exceptions import OrderExecutionError


_DEFAULT_COMPONENT = "app"

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()

def set_correlation_id(cid: str | None) -> None:
    _correlation_id_ctx.set(cid)


def _normalize_level(level: str | None = None) -> int:
    raw_level = str(level or getattr(settings, "LOG_LEVEL", "INFO") or "INFO")
    return getattr(logging, raw_level.upper(), logging.INFO)


def _json_enabled() -> bool:
    return str(getattr(settings, "LOG_FORMAT", "console")).strip().lower() == "json"


def _serialize_event(payload: dict[str, Any]) -> str:
    if _json_enabled():
        return json.dumps(payload, ensure_ascii=False, default=str)
    ordered = [f"event={payload.get('event', 'log')}"]
    for key in sorted(key for key in payload if key != "event"):
        ordered.append(f"{key}={payload[key]}")
    return " ".join(ordered)


def configure_logging(
    *,
    stream: io.TextIOBase | None = None,
    level: int | str | None = None,
    log_file: str | None = None,
    fmt: str | None = None,
) -> None:
    _configure_sentry()
    target = stream or sys.stdout
    handlers: list[logging.Handler] = []
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    else:
        handlers.append(logging.StreamHandler(target))
    if _json_enabled():
        # JSON formatter using python-json-logger
        try:
            from pythonjsonlogger import jsonlogger
            formatter = jsonlogger.JsonFormatter(
                fmt or "%(asctime)s %(levelname)s %(name)s %(component)s %(message)s"
            )
        except ImportError:
            formatter = logging.Formatter(fmt or "%(message)s")
    else:
        formatter = logging.Formatter(fmt or "%(message)s")
    for h in handlers:
        h.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    for h in handlers:
        root.addHandler(h)
    if level is not None:
        root.setLevel(
            level
            if isinstance(level, int)
            else getattr(logging, str(level).upper(), logging.INFO)
        )
    else:
        root.setLevel(_normalize_level())


def _configure_sentry() -> None:
    sentry_dsn = getattr(settings, "SENTRY_DSN", None)
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration

            sentry_sdk.init(
                dsn=sentry_dsn,
                integrations=[FlaskIntegration()],
                environment=getattr(settings, "ENVIRONMENT", "production"),
                traces_sample_rate=0.1,
            )
        except ImportError:
            pass


class BoundLogger:
    def __init__(self, name: str, **context: Any) -> None:
        self._logger = logging.getLogger(name)
        self._context = {"component": context.pop("component", name), **context}

    def bind(self, **context: Any) -> "BoundLogger":
        return BoundLogger(self._logger.name, **{**self._context, **context})

    def _emit(self, level: int, event: str, *args: Any, **fields: Any) -> None:
        if args:
            try:
                event = event % args
            except TypeError:
                event = event.format(*args)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **self._context,
            **fields,
            "event": event,
        }
        
        cid = _correlation_id_ctx.get()
        if cid is not None:
            payload["correlation_id"] = cid
            
        self._logger.log(level, _serialize_event(payload))

    def debug(self, event: str, *args: Any, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, *args, **fields)

    def info(self, event: str, *args: Any, **fields: Any) -> None:
        self._emit(logging.INFO, event, *args, **fields)

    def warning(self, event: str, *args: Any, **fields: Any) -> None:
        self._emit(logging.WARNING, event, *args, **fields)

    def error(self, event: str, *args: Any, **fields: Any) -> None:
        self._emit(logging.ERROR, event, *args, **fields)

    def exception(self, event: str, *args: Any, **fields: Any) -> None:
        error = fields.pop("error", None)
        if error is not None and "error_type" not in fields:
            fields["error_type"] = type(error).__name__
        self._emit(logging.ERROR, event, *args, **fields)


def get_logger(name: str, *, component: str | None = None) -> BoundLogger:
    if _structlog is not None:
        _ = _structlog
    return BoundLogger(name, component=component or _DEFAULT_COMPONENT)
