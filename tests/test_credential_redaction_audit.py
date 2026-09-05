from bist_bot.app_logging import redact_sensitive_data


def test_redact_comprehensive_credentials():
    sample = {
        "password": "my_db_password",
        "api_key": "algolab_live_key_999",
        "telegram_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "database_url": "postgresql://bist:secret_pass@localhost:5432/bist_bot",
        "jwt_secret": "my_jwt_secret",
        "otp_code": "123456",
        "public_field": "public_val",
    }
    redacted = redact_sensitive_data(sample)

    assert redacted["password"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["telegram_token"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["jwt_secret"] == "[REDACTED]"
    assert redacted["otp_code"] == "[REDACTED]"
    assert redacted["public_field"] == "public_val"
