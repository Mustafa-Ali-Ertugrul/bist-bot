"""Regression tests for log injection and info disclosure hardening (Round 8)."""

from __future__ import annotations

import json

from bist_bot.app_logging import _serialize_event, _strip_control_chars

# ---------------------------------------------------------------------------
# Control-character stripping
# ---------------------------------------------------------------------------


def test_strip_control_chars_removes_newlines():
    assert _strip_control_chars("hello\nworld") == "helloworld"


def test_strip_control_chars_removes_carriage_returns():
    assert _strip_control_chars("a\rb") == "ab"


def test_strip_control_chars_removes_null_bytes():
    assert _strip_control_chars("a\x00b") == "ab"


def test_strip_control_chars_preserves_normal_text():
    assert _strip_control_chars("normal text 123 !@#") == "normal text 123 !@#"


def test_strip_control_chars_handles_non_string():
    assert _strip_control_chars(42) == 42
    assert _strip_control_chars(None) is None


# ---------------------------------------------------------------------------
# Log serialization prevents injection
# ---------------------------------------------------------------------------


def test_console_serialize_strips_newlines_in_fields():
    """Newlines in field values must not create forged log lines."""
    payload = {"event": "test", "path": "/foo\n2026-01-01 FAKE"}
    result = _serialize_event(payload)
    # The newline must be stripped so the injected text doesn't start a new line.
    assert "\n" not in result
    assert result.startswith("event=test")


def test_json_serialize_strips_control_chars():
    """Even in JSON mode, control chars should be stripped."""
    from unittest.mock import patch

    payload = {"event": "test", "user_input": "bad\x00input"}
    with patch("bist_bot.app_logging._json_enabled", return_value=True):
        result = _serialize_event(payload)
    parsed = json.loads(result)
    assert "\x00" not in parsed["user_input"]
    assert parsed["user_input"] == "badinput"


# ---------------------------------------------------------------------------
# JWT error responses don't leak internal details
# ---------------------------------------------------------------------------


def test_jwt_unauthorized_response_no_detail():
    """JWT unauthorized response must not expose internal error strings."""
    from unittest.mock import MagicMock

    from bist_bot.config.settings import settings

    # The fixture 'app' from test_health_check provides a configured Flask app
    # with valid JWT settings. We test the handler behavior via Flask test client.
    with settings.override(
        JWT_SECRET_KEY="test-secret-health-check-fixture-0123456789",
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
    ):
        from bist_bot.dashboard import create_dashboard_app

        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=MagicMock(),
            broker=MagicMock(),
            circuit_breaker=MagicMock(),
        )
        application.config["TESTING"] = True
        with application.test_client() as client:
            # Request without auth token → triggers unauthorized_loader
            resp = client.get("/api/signals")
            data = resp.get_json()
            assert "detail" not in data
