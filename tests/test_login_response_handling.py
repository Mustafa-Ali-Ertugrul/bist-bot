"""Tests for Streamlit login/register response handling."""

from __future__ import annotations

from unittest.mock import MagicMock

from bist_bot.streamlit_app import _extract_token, _response_message


# ── _response_message tests ────────────────────────────────────────────────


def test_response_message_json_with_message():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {"message": "Invalid credentials"}
    assert _response_message(resp, "default") == "Invalid credentials"


def test_response_message_json_without_message_uses_status_code_fallback():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {"status": "error"}
    assert "Email veya sifre hatali" in _response_message(resp, "default")


def test_response_message_non_json_500_shows_server_error_message():
    resp = MagicMock()
    resp.status_code = 500
    resp.json.side_effect = ValueError("not json")
    resp.text = "<html><body>Internal Server Error</body></html>"
    result = _response_message(resp, "default")
    assert "API tarafinda hata" in result
    assert "500" in result


def test_response_message_empty_non_json_500_shows_server_error_message():
    resp = MagicMock()
    resp.status_code = 500
    resp.json.side_effect = ValueError("not json")
    resp.text = ""
    result = _response_message(resp, "default")
    assert "API tarafinda hata" in result
    assert "500" in result


def test_response_message_429_rate_limit():
    resp = MagicMock()
    resp.status_code = 429
    resp.json.return_value = {}
    assert "Cok fazla giris denemesi" in _response_message(resp, "default")


def test_response_message_401_unauthorized():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {}
    assert "Email veya sifre hatali" in _response_message(resp, "default")


def test_response_message_500_server_error():
    resp = MagicMock()
    resp.status_code = 502
    resp.json.return_value = {}
    result = _response_message(resp, "default")
    assert "API tarafinda hata" in result
    assert "502" in result


def test_response_message_non_json_429_shows_message():
    resp = MagicMock()
    resp.status_code = 429
    resp.json.side_effect = ValueError("not json")
    resp.text = ""
    result = _response_message(resp, "default")
    assert "Cok fazla giris denemesi" in result


# ── _extract_token tests ───────────────────────────────────────────────────


def test_extract_token_valid():
    resp = MagicMock()
    resp.json.return_value = {"access_token": "abc123", "status": "ok"}
    assert _extract_token(resp) == "abc123"


def test_extract_token_missing_key():
    resp = MagicMock()
    resp.json.return_value = {"status": "ok"}
    assert _extract_token(resp) is None


def test_extract_token_empty_string():
    resp = MagicMock()
    resp.json.return_value = {"access_token": ""}
    assert _extract_token(resp) is None


def test_extract_token_whitespace_only():
    resp = MagicMock()
    resp.json.return_value = {"access_token": "   "}
    assert _extract_token(resp) is None


def test_extract_token_non_dict_response():
    resp = MagicMock()
    resp.json.return_value = ["not", "a", "dict"]
    assert _extract_token(resp) is None


def test_extract_token_invalid_json():
    resp = MagicMock()
    resp.json.side_effect = ValueError("not json")
    assert _extract_token(resp) is None


def test_extract_token_strips_whitespace():
    resp = MagicMock()
    resp.json.return_value = {"access_token": "  token123  "}
    assert _extract_token(resp) == "token123"
