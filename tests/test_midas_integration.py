"""Tests for the Midas agent integration client."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from bist_bot.integrations.midas import MidasClient
except ImportError:
    pytest.skip("Cannot import midas client (missing dependencies)", allow_module_level=True)


class TestMidasClientConfiguration:
    """Test MidasClient configuration and environment variable handling."""

    def test_default_disabled(self) -> None:
        """Client should be disabled by default when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            client = MidasClient()
            assert client.enabled is False
            assert client.is_configured() is False

    def test_enabled_via_env(self) -> None:
        """MIDAS_ENABLED=true should enable the client."""
        env = {
            "MIDAS_API_KEY": "test-key",
            "MIDAS_API_URL": "https://api.midas.example.com",
            "MIDAS_AGENT_ID": "agent-1",
            "MIDAS_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            client = MidasClient()
            assert client.enabled is True
            assert client.is_configured() is True

    def test_enabled_via_constructor(self) -> None:
        """Constructor arguments should override env vars."""
        client = MidasClient(
            api_key="k",
            api_url="https://x",
            agent_id="a",
            enabled=True,
        )
        assert client.api_key == "k"
        assert client.api_url == "https://x"
        assert client.agent_id == "a"
        assert client.enabled is True

    def test_missing_api_key(self) -> None:
        """Client should be unconfigured if API key is missing."""
        env = {
            "MIDAS_API_URL": "https://api.midas.example.com",
            "MIDAS_AGENT_ID": "agent-1",
            "MIDAS_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            client = MidasClient()
            assert client.is_configured() is False

    def test_missing_url(self) -> None:
        """Client should be unconfigured if API URL is missing."""
        env = {
            "MIDAS_API_KEY": "test-key",
            "MIDAS_AGENT_ID": "agent-1",
            "MIDAS_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            client = MidasClient()
            assert client.is_configured() is False

    def test_missing_agent_id(self) -> None:
        """Client should be unconfigured if agent ID is missing."""
        env = {
            "MIDAS_API_KEY": "test-key",
            "MIDAS_API_URL": "https://api.midas.example.com",
            "MIDAS_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            client = MidasClient()
            assert client.is_configured() is False


class TestMidasClientSendSignal:
    """Test MidasClient.send_signal() behaviour."""

    def test_send_signal_not_configured(self) -> None:
        """send_signal should return False when client is not configured."""
        client = MidasClient()
        result = client.send_signal({"ticker": "THYAO.IS"})
        assert result is False

    def test_send_signal_success(self) -> None:
        """send_signal should return True on a 200 response."""
        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch(
            "bist_bot.integrations.midas.requests.post", return_value=mock_response
        ) as mock_post:
            result = client.send_signal({"ticker": "THYAO.IS", "score": 75.0})

        assert result is True
        # Verify the request was made correctly
        call = mock_post.call_args
        assert call.args[0] == "https://api.midas.example.com/signals"
        assert call.kwargs["headers"]["Authorization"] == "Bearer k"
        assert call.kwargs["json"]["agent_id"] == "agent-1"
        assert call.kwargs["json"]["ticker"] == "THYAO.IS"

    def test_send_signal_auth_failure(self) -> None:
        """send_signal should return False on 401 without retrying."""
        client = MidasClient(
            api_key="bad-key",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch(
            "bist_bot.integrations.midas.requests.post", return_value=mock_response
        ) as mock_post:
            result = client.send_signal({"ticker": "THYAO.IS"})

        assert result is False
        # Should only try once for auth failures
        assert mock_post.call_count == 1

    def test_send_signal_timeout(self) -> None:
        """send_signal should retry on timeout and ultimately return False."""
        import requests as real_requests

        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )

        with patch(
            "bist_bot.integrations.midas.requests.post",
            side_effect=real_requests.Timeout("connection timed out"),
        ) as mock_post:
            result = client.send_signal({"ticker": "THYAO.IS"})

        assert result is False
        # Should retry MAX_RETRY_ATTEMPTS times
        assert mock_post.call_count == 3

    def test_send_signal_request_error_no_retry(self) -> None:
        """send_signal should NOT retry on generic RequestException."""
        import requests as real_requests

        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )

        with patch(
            "bist_bot.integrations.midas.requests.post",
            side_effect=real_requests.ConnectionError("network unreachable"),
        ) as mock_post:
            result = client.send_signal({"ticker": "THYAO.IS"})

        assert result is False
        # Connection errors are not retried
        assert mock_post.call_count == 1

    def test_send_signal_server_error_retries(self) -> None:
        """send_signal should retry on 5xx server errors."""
        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch(
            "bist_bot.integrations.midas.requests.post", return_value=mock_response
        ) as mock_post:
            result = client.send_signal({"ticker": "THYAO.IS"})

        assert result is False
        # Should retry MAX_RETRY_ATTEMPTS times
        assert mock_post.call_count == 3

    def test_send_signal_includes_agent_id_in_payload(self) -> None:
        """send_signal should inject agent_id into the payload."""
        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="my-agent",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch(
            "bist_bot.integrations.midas.requests.post", return_value=mock_response
        ) as mock_post:
            client.send_signal({"ticker": "ASELS.IS", "score": 50.0})

        payload = mock_post.call_args.kwargs["json"]
        assert payload["agent_id"] == "my-agent"
        assert payload["ticker"] == "ASELS.IS"
        assert payload["score"] == 50.0

    def test_send_signal_strips_trailing_slash_from_url(self) -> None:
        """Trailing slash on the API URL should not produce double slashes."""
        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com/",
            agent_id="agent-1",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch(
            "bist_bot.integrations.midas.requests.post", return_value=mock_response
        ) as mock_post:
            client.send_signal({"ticker": "THYAO.IS"})

        assert mock_post.call_args.args[0] == "https://api.midas.example.com/signals"


class TestMidasClientHeartbeat:
    """Test MidasClient.heartbeat() behaviour."""

    def test_heartbeat_not_configured(self) -> None:
        """heartbeat should return False when not configured."""
        client = MidasClient()
        assert client.heartbeat() is False

    def test_heartbeat_success(self) -> None:
        """heartbeat should return True on 2xx response."""
        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("bist_bot.integrations.midas.requests.post", return_value=mock_response):
            assert client.heartbeat() is True

    def test_heartbeat_failure(self) -> None:
        """heartbeat should return False on 5xx response."""
        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("bist_bot.integrations.midas.requests.post", return_value=mock_response):
            assert client.heartbeat() is False

    def test_heartbeat_network_error(self) -> None:
        """heartbeat should return False on network errors."""
        import requests as real_requests

        client = MidasClient(
            api_key="k",
            api_url="https://api.midas.example.com",
            agent_id="agent-1",
            enabled=True,
        )
        with patch(
            "bist_bot.integrations.midas.requests.post",
            side_effect=real_requests.ConnectionError(),
        ):
            assert client.heartbeat() is False
