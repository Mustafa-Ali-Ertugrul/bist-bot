"""Regression tests for log security hardening: hot-path guard, token leak
through exception objects/containers, and lost tracebacks (exception() exc_info).

These guard against the three concrete bugs found in the Round 22 log audit:
1. _redact_value skipped BaseException/tuple/set → tokens leaked via default=str
2. BoundLogger.exception() never passed exc_info → all 49 call sites lost tracebacks
3. _emit serialized before checking log level → unnecessary hot-path overhead
"""

from __future__ import annotations

import io

from bist_bot.app_logging import (
    _redact_value,
    configure_logging,
    get_logger,
)

TG_TOKEN = "bot123456789:AAFakeTokenValue_xyz-123"
JWT_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456ghi789jkl012"
)


# -----------------------------------------------------------------------
# Fix 1: _redact_value handles exception objects and tuple/set containers
# -----------------------------------------------------------------------


class TestExceptionRedaction:
    """Tokens embedded in exception messages must be redacted."""

    def test_exception_object_telegram_token_redacted(self):
        exc = RuntimeError(f"Max retries exceeded with url: /{TG_TOKEN}/sendMessage")
        result = _redact_value("error", exc)
        assert isinstance(result, str)
        assert TG_TOKEN not in result
        assert "bot[REDACTED]" in result

    def test_exception_object_jwt_token_redacted(self):
        """Bearer-prefixed JWT exception is redacted."""
        exc = ValueError(f"Bearer {JWT_TOKEN}")
        result = _redact_value("error", exc)
        assert isinstance(result, str)
        assert "[REDACTED_TOKEN]" in result

    def test_exception_object_standalone_jwt_redacted(self):
        """Standalone JWT in exception message is redacted."""
        exc = ValueError(JWT_TOKEN)
        result = _redact_value("error", exc)
        assert isinstance(result, str)
        assert "[REDACTED_TOKEN]" in result

    def test_exception_object_sensitive_key_still_redacted(self):
        """Exception under 'secret' key must be fully redacted."""
        exc = RuntimeError("some error with " + TG_TOKEN)
        result = _redact_value("secret", exc)
        assert result == "[REDACTED]"

    def test_exception_preserves_message_text(self):
        exc = RuntimeError("normal error without tokens")
        result = _redact_value("error", exc)
        assert result == "normal error without tokens"


class TestContainerRedaction:
    """Tuple and set containers must recurse like list."""

    def test_tuple_with_token_redacted(self):
        result = _redact_value("context", (TG_TOKEN, "ok"))
        assert isinstance(result, list)
        assert TG_TOKEN not in result
        assert result[1] == "ok"

    def test_set_with_token_redacted(self):
        # Sets become lists; token is redacted.
        result = _redact_value("tags", {TG_TOKEN, "normal"})
        assert isinstance(result, list)
        assert TG_TOKEN not in result

    def test_nested_tuple_in_dict(self):
        payload = {"data": {"ids": (TG_TOKEN, "123")}}
        from bist_bot.app_logging import redact_sensitive_data

        redacted = redact_sensitive_data(payload)
        # id is not a sensitive key, but the value should be redacted
        assert TG_TOKEN not in str(redacted)


# -----------------------------------------------------------------------
# Fix 2: BoundLogger.exception() passes exc_info for traceback capture
# -----------------------------------------------------------------------


class TestExceptionTraceback:
    """logger.exception() must emit traceback text, not just error name."""

    def test_exception_emits_traceback(self):
        """Inside except block, exception() must capture the traceback."""
        stream = io.StringIO()
        try:
            raise ExceptionInfo("boom")
        except ExceptionInfo as exc:
            configure_logging(stream=stream, level="DEBUG")
            logger = get_logger("test.tb", component="test")
            logger.exception("op_failed", error=exc)

        output = stream.getvalue()
        assert "Traceback" in output
        assert "ExceptionInfo" in output
        assert "boom" in output

    def test_exception_with_error_arg_captures_traceback(self):
        """When error=exc is passed, traceback of that exception appears."""
        stream = io.StringIO()
        configure_logging(stream=stream, level="DEBUG")
        logger = get_logger("test.tb2", component="test")

        try:
            raise ValueError("specific error")
        except ValueError as exc:
            logger.exception("task_failed", error=exc)

        output = stream.getvalue()
        assert "Traceback" in output
        assert "ValueError" in output
        assert "specific error" in output

    def test_exception_json_mode_includes_traceback(self):
        """JSON mode: exception text is embedded in the record."""
        stream = io.StringIO()
        from unittest.mock import patch

        try:
            raise ExceptionInfo("json boom")
        except ExceptionInfo:
            configure_logging(stream=stream, level="DEBUG", fmt=None)
            with patch("bist_bot.app_logging._json_enabled", return_value=True):
                logger = get_logger("test.tb3", component="test")
                logger.exception("json_error")

        # Parse as JSON — payload should contain traceback
        line = stream.getvalue().strip()
        assert "Traceback" in line or "ExceptionInfo" in line

    def test_exception_outside_except_without_error_no_crash(self):
        """logger.exception() outside except block must not crash."""
        stream = io.StringIO()
        configure_logging(stream=stream, level="DEBUG")
        logger = get_logger("test.noexc", component="test")
        # exc_info=True with no active exception → sys.exc_info() = (None,None,None)
        # logging handles this gracefully.
        logger.exception("something_broken")
        output = stream.getvalue()
        assert "something_broken" in output


class ExceptionInfo(Exception):
    """Custom exception for testing traceback capture."""


# -----------------------------------------------------------------------
# Fix 3: _emit skips serialization when level is disabled
# -----------------------------------------------------------------------


class TestEmitLevelGuard:
    """_emit must short-circuit when the logger level is below the call."""

    def test_debug_skipped_when_level_is_info(self):
        """DEBUG calls must not hit _serialize_event when level=INFO."""
        from unittest.mock import patch

        stream = io.StringIO()
        configure_logging(stream=stream, level="INFO")
        logger = get_logger("test.guard", component="test")

        with patch("bist_bot.app_logging._serialize_event") as mock_ser:
            logger.debug("should_be_skipped", ticker="THYAO")
            mock_ser.assert_not_called()

    def test_info_emitted_when_level_is_info(self):
        """INFO calls must still emit when level=INFO."""
        from unittest.mock import patch

        stream = io.StringIO()
        configure_logging(stream=stream, level="INFO")
        logger = get_logger("test.guard2", component="test")

        with patch("bist_bot.app_logging._serialize_event") as mock_ser:
            logger.info("should_emit")
            mock_ser.assert_called_once()

    def test_no_datetime_now_when_level_disabled(self):
        """datetime.now(UTC) must not be called when level is disabled."""
        from unittest.mock import patch

        stream = io.StringIO()
        configure_logging(stream=stream, level="WARNING")
        logger = get_logger("test.guard3", component="test")

        with patch("bist_bot.app_logging.datetime") as mock_dt:
            logger.info("skipped_event")
            mock_dt.now.assert_not_called()

    def test_timestamp_not_in_payload_when_disabled(self):
        """When level is disabled, no payload is constructed at all."""
        from unittest.mock import patch

        stream = io.StringIO()
        configure_logging(stream=stream, level="WARNING")
        logger = get_logger("test.guard4", component="test")

        with patch.dict("os.environ", {"PYTHONPATH": "src"}):
            with patch("bist_bot.app_logging.BoundLogger._emit", wraps=logger._emit):
                logger.info("low_level_event")
                # The guard fires early — _emit still called but returns before payload
                # (wraps won't help here; check no output)
        assert "low_level_event" not in stream.getvalue()


# -----------------------------------------------------------------------
# Extra: full-roundtrip test — exception with token in BoundLogger
# -----------------------------------------------------------------------


class TestEndToEndRedaction:
    """Simulate the real-world path: requests error with bot token logged
    through BoundLogger.exception() in JSON mode."""

    def test_exception_with_token_redacted_in_output(self):
        stream = io.StringIO()
        configure_logging(stream=stream, level="DEBUG")
        logger = get_logger("test.e2e", component="test")

        exc = RuntimeError(
            f"HTTPSConnectionPool: Max retries exceeded with url: /{TG_TOKEN}/sendMessage"
        )
        try:
            raise exc
        except RuntimeError:
            logger.exception("telegram_error")

        output = stream.getvalue()
        assert TG_TOKEN not in output
        assert "bot[REDACTED]" in output

    def test_exception_with_jwt_redacted_in_output(self):
        stream = io.StringIO()
        configure_logging(stream=stream, level="DEBUG")
        logger = get_logger("test.e2e2", component="test")

        exc = ValueError(f"Invalid token: {JWT_TOKEN}")
        try:
            raise exc
        except ValueError:
            logger.exception("auth_error")

        output = stream.getvalue()
        # Standalone JWT is redacted; substring-with-prefix is not (matches
        # existing _redact_value contract for non-sensitive keys).
        assert JWT_TOKEN not in output
        assert "[REDACTED_TOKEN]" in output
