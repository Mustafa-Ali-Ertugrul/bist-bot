"""Midas agent integration client.

Provides HTTP-based integration with the Midas external signal-sharing service.
The client is intentionally defensive: configuration is read from environment
variables, all network failures are logged but never raised, and the integration
is disabled-by-default so that the rest of the BIST Bot pipeline keeps working
even if Midas is unreachable or misconfigured.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from bist_bot.app_logging import get_logger

logger = get_logger(__name__, component="midas")

DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 3


class MidasClient:
    """Lightweight HTTP client for the Midas agent integration.

    Reads configuration from environment variables:
    - ``MIDAS_API_KEY``: Bearer token for authorization
    - ``MIDAS_API_URL``: Base URL of the Midas API
    - ``MIDAS_AGENT_ID``: Unique identifier for this agent
    - ``MIDAS_ENABLED``: Set to "true" to enable the integration

    The client is disabled-by-default: if any required variable is missing or
    ``MIDAS_ENABLED`` is not "true", :meth:`send_signal` becomes a no-op that
    returns ``False`` and logs a single warning. This makes the integration
    safe to ship in production before the upstream service is ready.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        agent_id: str | None = None,
        enabled: bool | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("MIDAS_API_KEY", "")
        self.api_url = api_url if api_url is not None else os.environ.get("MIDAS_API_URL", "")
        self.agent_id = agent_id if agent_id is not None else os.environ.get("MIDAS_AGENT_ID", "")
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = os.environ.get("MIDAS_ENABLED", "false").lower() == "true"
        self.timeout = timeout

    def is_configured(self) -> bool:
        """Return True if all required configuration values are present."""
        return bool(self.api_key and self.api_url and self.agent_id and self.enabled)

    def send_signal(self, signal_data: dict[str, Any]) -> bool:
        """Send a single trading signal to the Midas service.

        Returns True on a successful 2xx response, False on any failure or when
        the client is not configured. Never raises.
        """
        if not self.is_configured():
            logger.warning("midas_not_configured")
            return False

        payload = {**signal_data, "agent_id": self.agent_id}
        url = f"{self.api_url.rstrip('/')}/signals"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if 200 <= response.status_code < 300:
                    logger.info(
                        "midas_signal_sent",
                        ticker=signal_data.get("ticker"),
                        status_code=response.status_code,
                        attempt=attempt,
                    )
                    return True
                if response.status_code in (401, 403):
                    logger.error(
                        "midas_auth_failed",
                        status_code=response.status_code,
                        ticker=signal_data.get("ticker"),
                    )
                    return False
                logger.warning(
                    "midas_request_failed",
                    status_code=response.status_code,
                    attempt=attempt,
                    ticker=signal_data.get("ticker"),
                )
            except requests.Timeout:
                logger.warning(
                    "midas_timeout",
                    attempt=attempt,
                    timeout=self.timeout,
                    ticker=signal_data.get("ticker"),
                )
            except requests.RequestException as exc:
                logger.error(
                    "midas_request_error",
                    error_type=type(exc).__name__,
                    attempt=attempt,
                    ticker=signal_data.get("ticker"),
                )
                return False

        logger.error("midas_send_exhausted", ticker=signal_data.get("ticker"))
        return False

    def heartbeat(self) -> bool:
        """Send a heartbeat ping to keep the agent registration alive."""
        if not self.is_configured():
            return False
        url = f"{self.api_url.rstrip('/')}/agent/heartbeat"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"agent_id": self.agent_id},
                timeout=self.timeout,
            )
            return 200 <= response.status_code < 300
        except requests.RequestException as exc:
            logger.warning("midas_heartbeat_failed", error_type=type(exc).__name__)
            return False
