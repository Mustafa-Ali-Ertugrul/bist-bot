"""Tests for Streamlit login/register response handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bist_bot.streamlit_app import _extract_token, _handle_shell_action, _response_message

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


def test_handle_shell_action_logout_resets_auth_state():
    session_state = SimpleNamespace(
        auth_token="token",
        auth_email="user@example.com",
        is_authenticated=True,
        app_bootstrapped=True,
        just_logged_in=True,
    )

    with (
        patch("bist_bot.streamlit_app.st.session_state", session_state),
        patch("bist_bot.streamlit_app.set_active_page") as mock_set_active_page,
    ):
        _handle_shell_action("logout")

    assert session_state.auth_token is None
    assert session_state.auth_email == ""
    assert session_state.is_authenticated is False
    assert session_state.app_bootstrapped is False
    assert session_state.just_logged_in is False
    mock_set_active_page.assert_called_once_with("dashboard")


def test_handle_shell_action_page_routes_through_set_active_page():
    with patch("bist_bot.streamlit_app.set_active_page") as mock_set_active_page:
        _handle_shell_action("page:signals")

    mock_set_active_page.assert_called_once_with("signals")


def test_handle_shell_action_ignores_invalid_page_target():
    with patch("bist_bot.streamlit_app.set_active_page") as mock_set_active_page:
        _handle_shell_action("page:not-a-real-page")

    mock_set_active_page.assert_not_called()
