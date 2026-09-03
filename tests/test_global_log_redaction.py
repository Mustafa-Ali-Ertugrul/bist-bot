import json
from bist_bot.app_logging import redact_sensitive_data, _serialize_event


def test_redact_sensitive_data():
    payload = {
        "event": "user_login",
        "username": "trader1",
        "password": "super_secret_password",
        "api_key": "secret_key_12345",
        "nested": {
            "jwt_token": "bearer xyz",
            "normal_field": "ok_value",
        },
    }
    redacted = redact_sensitive_data(payload)
    assert redacted["username"] == "trader1"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["jwt_token"] == "[REDACTED]"
    assert redacted["nested"]["normal_field"] == "ok_value"


def test_serialize_event_redacts_credentials():
    payload = {
        "event": "auth_event",
        "token": "sensitive_jwt_token",
        "data": "public_data",
    }
    serialized = _serialize_event(payload)
    assert "sensitive_jwt_token" not in serialized
    assert "[REDACTED]" in serialized
    assert "public_data" in serialized
