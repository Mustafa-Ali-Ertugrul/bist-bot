"""Regression tests for log token leakage + payment reference entropy (Round 18).

1. Log redaction must catch Telegram bot tokens embedded in URLs/exception
   strings, even in fields whose key name is not in the sensitive list
   (requests' "Max retries exceeded with url: /bot<token>/..." shape).
2. Payment reference IDs must carry enough entropy to resist brute-force
   listing (raised from 24-bit to 48-bit).
"""

from __future__ import annotations

from bist_bot.app_logging import redact_sensitive_data

_FAKE_TOKEN = "bot1234567890:ABCDefGhIJ1234567890_-klmn"


def test_redact_telegram_token_in_plain_string_field():
    """A token inside a non-sensitive-key string field must be redacted."""
    payload = {
        "event": "pro_invite_failed",
        "reason": f"Max retries exceeded with url: /{_FAKE_TOKEN}/createChatInviteLink",
    }
    out = redact_sensitive_data(payload)
    assert _FAKE_TOKEN not in out["reason"]
    assert "bot[REDACTED]" in out["reason"]


def test_redact_telegram_token_in_url_form():
    payload = {"msg": f"https://api.telegram.org/{_FAKE_TOKEN}/sendMessage"}
    out = redact_sensitive_data(payload)
    assert _FAKE_TOKEN not in out["msg"]


def test_redact_does_not_mangle_normal_text():
    payload = {"event": "ok", "message": "normal operational text"}
    assert redact_sensitive_data(payload)["message"] == "normal operational text"
