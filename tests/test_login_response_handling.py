"""Tests for Streamlit login/register response handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bist_bot.streamlit_app import (
    _complete_auth,
    _extract_token,
    _handle_query_actions,
    _render_sidebar_news_html,
    _response_message,
)

# ── _response_message tests ────────────────────────────────────────────────


def test_response_message_json_with_message():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {"message": "Invalid credentials"}
    assert _response_message(resp, "default") == "Invalid credentials"


def test_render_sidebar_news_html_links_to_news_site():
    html_output = _render_sidebar_news_html(
        [
            {
                "title": "BIST 100 test haberi",
                "url": "https://example.com/news",
                "source": "Kaynak",
                "published_at": "Wed, 20 May",
            }
        ]
    )

    assert "BIST100 Haberleri" in html_output
    assert "BIST 100 test haberi" in html_output
    assert "href='https://example.com/news'" in html_output
    assert "target='_blank'" in html_output


def test_render_sidebar_news_html_escapes_untrusted_news_fields():
    html_output = _render_sidebar_news_html(
        [
            {
                "title": "<script>alert(1)</script>",
                "url": "https://example.com/?q='bad'",
                "source": "<b>Kaynak</b>",
                "published_at": "",
            }
        ]
    )

    assert "<script>" not in html_output
    assert "&lt;script&gt;" in html_output
    assert "&#x27;bad&#x27;" in html_output


def test_response_message_json_without_message_uses_status_code_fallback():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {"status": "error"}
    assert "E-posta veya şifre hatalı" in _response_message(resp, "default")


def test_response_message_non_json_500_shows_server_error_message():
    resp = MagicMock()
    resp.status_code = 500
    resp.json.side_effect = ValueError("not json")
    resp.text = "<html><body>Internal Server Error</body></html>"
    result = _response_message(resp, "default")
    assert "API tarafında hata" in result
    assert "500" in result


def test_response_message_empty_non_json_500_shows_server_error_message():
    resp = MagicMock()
    resp.status_code = 500
    resp.json.side_effect = ValueError("not json")
    resp.text = ""
    result = _response_message(resp, "default")
    assert "API tarafında hata" in result
    assert "500" in result


def test_response_message_429_rate_limit():
    resp = MagicMock()
    resp.status_code = 429
    resp.json.return_value = {}
    assert "Çok fazla giriş denemesi" in _response_message(resp, "default")


def test_response_message_401_unauthorized():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {}
    assert "E-posta veya şifre hatalı" in _response_message(resp, "default")


def test_response_message_500_server_error():
    resp = MagicMock()
    resp.status_code = 502
    resp.json.return_value = {}
    result = _response_message(resp, "default")
    assert "API tarafında hata" in result
    assert "502" in result


def test_response_message_non_json_429_shows_message():
    resp = MagicMock()
    resp.status_code = 429
    resp.json.side_effect = ValueError("not json")
    resp.text = ""
    result = _response_message(resp, "default")
    assert "Çok fazla giriş denemesi" in result


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


def test_complete_auth_sets_session_and_routes_dashboard():
    session_state = SimpleNamespace(
        auth_token=None,
        auth_email="",
        is_authenticated=False,
        app_bootstrapped=True,
        just_logged_in=False,
    )
    query_params = {}

    with (
        patch("bist_bot.streamlit_app.st.session_state", session_state),
        patch("bist_bot.streamlit_app.st.query_params", query_params),
        patch("bist_bot.streamlit_app.st.rerun") as mock_rerun,
    ):
        _complete_auth("user@example.com", "token123")

    assert session_state.auth_token == "token123"
    assert session_state.auth_email == "user@example.com"
    assert session_state.is_authenticated is True
    assert session_state.app_bootstrapped is False
    assert session_state.just_logged_in is True
    assert query_params["page"] == "dashboard"
    mock_rerun.assert_called_once_with()


def test_handle_query_actions_logout_resets_auth_state():
    session_state = SimpleNamespace(
        auth_token="token",
        auth_email="user@example.com",
        is_authenticated=True,
        app_bootstrapped=True,
        just_logged_in=True,
    )
    query_params = {"action": "logout"}

    with (
        patch("bist_bot.streamlit_app.st.session_state", session_state),
        patch("bist_bot.streamlit_app.st.query_params", query_params),
        patch("bist_bot.streamlit_app.st.rerun") as mock_rerun,
    ):
        _handle_query_actions()

    assert session_state.auth_token is None
    assert session_state.auth_email == ""
    assert session_state.is_authenticated is False
    assert session_state.app_bootstrapped is False
    assert session_state.just_logged_in is False
    assert "action" not in query_params
    mock_rerun.assert_called_once()


def test_handle_query_actions_toggle_sidebar():
    class SessionStateStub(dict):
        def __getattr__(self, key):
            return self[key]

        def __setattr__(self, key, value):
            self[key] = value

    session_state = SessionStateStub(sidebar_collapsed=False)
    query_params = {"action": "toggle_sidebar"}

    with (
        patch("bist_bot.streamlit_app.st.session_state", session_state),
        patch("bist_bot.streamlit_app.st.query_params", query_params),
        patch("bist_bot.streamlit_app.st.rerun") as mock_rerun,
    ):
        _handle_query_actions()

    assert session_state.sidebar_collapsed is True
    assert "action" not in query_params
    mock_rerun.assert_called_once()


def test_handle_query_actions_ignores_invalid_action():
    class SessionStateStub(dict):
        def __getattr__(self, key):
            return self[key]

        def __setattr__(self, key, value):
            self[key] = value

    session_state = SessionStateStub(sidebar_collapsed=False)
    query_params = {"action": "not-a-real-action"}

    with (
        patch("bist_bot.streamlit_app.st.session_state", session_state),
        patch("bist_bot.streamlit_app.st.query_params", query_params),
        patch("bist_bot.streamlit_app.st.rerun") as mock_rerun,
    ):
        _handle_query_actions()

    assert session_state.sidebar_collapsed is False
    assert "action" in query_params
    mock_rerun.assert_not_called()
