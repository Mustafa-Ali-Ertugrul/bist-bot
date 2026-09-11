"""Minimal structured logging helpers with JSON and console renderers."""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

try:
    import structlog as _structlog  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    _structlog = None

_DEFAULT_COMPONENT = "app"

_SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "api_key",
    "jwt",
    "authorization",
    "key",
    "otp",
    "credential",
    "cookie",
    "session",
    "private",
    "cert",
    "webhook",
}

_JWT_PATTERN_RE = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")

# Non-anchored variant for traceback/exception text where a JWT appears inside
# a larger message (e.g. "Invalid token: eyJ...") — matches the 3-segment JWT
# shape anywhere in the line.
_JWT_FRAGMENT_RE = re.compile(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")

# Telegram bot tokens embedded in URLs/errors: bot123456:ABC-DEF...
# requests' hata metinleri tam URL'i taşır (örn. Max retries exceeded with url:
# /bot<token>/createChatInviteLink) — "error" gibi hassas-sayılmayan anahtarlar
# da bu deseni loga taşıyabilir; değer düzeyinde redakte edilir.
_TG_TOKEN_RE = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]+")


class _TracebackRedactingFilter(logging.Filter):
    """Redact bot tokens from exception text appended by logging handlers.

    ``BoundLogger`` redacts structured payload fields, but the *traceback* is
    formatted by the ``logging`` Formatter after our serialize/redact step, so
    tokens inside exception messages (e.g. requests errors carrying the Telegram
    URL with ``/bot<token>/...``) could otherwise reach the sink verbatim.
    Formatting the exception text ourselves and storing it on
    ``record.exc_text`` makes every Formatter reuse the redacted version.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.exc_info or getattr(record, "exc_text", None):
            return True
        try:
            text = "".join(traceback.format_exception(*record.exc_info))
            text = _TG_TOKEN_RE.sub("bot[REDACTED]", text)
            text = _JWT_FRAGMENT_RE.sub("[REDACTED_TOKEN]", text)
            record.exc_text = text
        except Exception:  # pragma: no cover - never break logging
            pass
        return True


def _redact_value(key: str, val: Any) -> Any:
    key_lower = str(key).lower()
    if any(s in key_lower for s in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(val, BaseException):
        val = str(val)  # fall through to string/redaction
    if isinstance(val, str):
        val = _TG_TOKEN_RE.sub("bot[REDACTED]", val)
        val_trimmed = val.strip()
        if val_trimmed.startswith("Bearer eyJ") or _JWT_PATTERN_RE.match(val_trimmed):
            return "[REDACTED_TOKEN]"
        return val
    if isinstance(val, dict):
        return {k: _redact_value(k, v) for k, v in val.items()}
    if isinstance(val, list | tuple | set):
        return [_redact_value(key, item) for item in val]
    return val


def redact_sensitive_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive fields (passwords, tokens, keys) from log payload."""
    return {k: _redact_value(k, v) for k, v in payload.items()}


_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()


def set_correlation_id(cid: str | None) -> None:
    _correlation_id_ctx.set(cid)


def _normalize_level(level: str | None = None) -> int:
    from bist_bot.config.settings import settings

    raw_level = str(level or getattr(settings, "LOG_LEVEL", "INFO") or "INFO")
    return getattr(logging, raw_level.upper(), logging.INFO)


def _json_enabled() -> bool:
    from bist_bot.config.settings import settings

    return str(getattr(settings, "LOG_FORMAT", "console")).strip().lower() == "json"


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _strip_control_chars(val: Any) -> Any:
    """Strip control characters that could forge log lines in console mode."""
    if isinstance(val, str):
        return _CONTROL_CHAR_RE.sub("", val)
    return val


def _serialize_event(payload: dict[str, Any]) -> str:
    sanitized = redact_sensitive_data(payload)
    # Strip control chars to prevent log injection via \n / \r in field values.
    sanitized = {k: _strip_control_chars(v) for k, v in sanitized.items()}
    if _json_enabled():
        return json.dumps(sanitized, ensure_ascii=False, default=str)
    ordered = [f"event={sanitized.get('event', 'log')}"]
    for key in sorted(key for key in sanitized if key != "event"):
        ordered.append(f"{key}={sanitized[key]}")
    return " ".join(ordered)


def _make_console_safe(stream: Any) -> Any:
    """Make the log stream lossless-safe for consoles with a limited encoding.

    Windows consoles default to a legacy codepage (e.g. cp1252) where emoji-heavy
    log lines raise ``UnicodeEncodeError`` inside ``StreamHandler.emit``. Reconfiguring
    with ``errors="replace"`` keeps the existing encoding (so locale text such as
    Turkish renders unchanged) and degrades unencodable characters to ``?`` instead
    of raising.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return stream
    try:
        reconfigure(errors="replace")
    except (OSError, ValueError, AttributeError):  # pragma: no cover - env dependent
        pass
    return stream


def configure_logging(
    *,
    stream: io.TextIOBase | None = None,
    level: int | str | None = None,
    log_file: str | None = None,
    fmt: str | None = None,
) -> None:
    _configure_sentry()
    target = _make_console_safe(stream or sys.stdout)
    handlers: list[logging.Handler] = []
    if log_file:
        # File logs default to the locale codepage otherwise; force UTF-8 so any
        # character written via ensure_ascii=False survives round-trips.
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    else:
        handlers.append(logging.StreamHandler(target))
    if _json_enabled():
        # JSON formatter using python-json-logger
        try:
            from pythonjsonlogger import jsonlogger

            formatter = jsonlogger.JsonFormatter(
                fmt or "%(asctime)s %(levelname)s %(name)s %(component)s %(message)s"
            )
        except ImportError:  # pragma: no cover - optional dependency
            formatter = logging.Formatter(fmt or "%(message)s")
    else:
        formatter = logging.Formatter(fmt or "%(message)s")
    for h in handlers:
        h.setFormatter(formatter)
        h.addFilter(_TracebackRedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    for h in handlers:
        root.addHandler(h)
    if level is not None:
        root.setLevel(
            level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.INFO)
        )
    else:
        root.setLevel(_normalize_level())


def _configure_sentry() -> None:
    from bist_bot.config.settings import settings

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
        except ImportError:  # pragma: no cover - optional dependency
            pass


class BoundLogger:
    def __init__(self, name: str, **context: Any) -> None:
        self._logger = logging.getLogger(name)
        self._context = {"component": context.pop("component", name), **context}

    def bind(self, **context: Any) -> BoundLogger:
        return BoundLogger(self._logger.name, **{**self._context, **context})

    def _emit(
        self,
        level: int,
        event: str,
        *args: Any,
        exc_info: Any = None,
        **fields: Any,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return
        if args:
            try:
                event = event % args
            except TypeError:
                event = event.format(*args)
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            **self._context,
            **fields,
            "event": event,
        }

        cid = _correlation_id_ctx.get()
        if cid is not None:
            payload["correlation_id"] = cid

        # Pass traceback through to logging handlers (exception() sets this).
        # Redact tokens in the formatted exception text before the formatter
        # appends it to the message — this closes the leak where bot tokens in
        # HTTP error messages survived redaction because exc_text is formatted
        # by the logging Formatter, outside our serialize/redact pipeline.
        _tg_redact_kw: dict[str, Any] = {}
        if exc_info is True:
            exc_info = sys.exc_info()
        if exc_info:
            _tg_redact_kw["exc_info"] = exc_info

        self._logger.log(level, _serialize_event(payload), **_tg_redact_kw)

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
        # Default to the active exception (like stdlib logging.exception); when
        # an explicit exception instance is supplied (e.g. Flask error handlers)
        # prefer it so the real traceback is captured even without an active
        # exception frame.
        exc_info = fields.pop("exc_info", True)
        if isinstance(error, BaseException):
            exc_info = error
        self._emit(logging.ERROR, event, *args, exc_info=exc_info, **fields)


def get_logger(name: str, *, component: str | None = None) -> BoundLogger:
    if _structlog is not None:
        _ = _structlog
    return BoundLogger(name, component=component or _DEFAULT_COMPONENT)
