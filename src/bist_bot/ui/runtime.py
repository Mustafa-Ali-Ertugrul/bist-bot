"""Compatibility surface for the modular Streamlit runtime helpers."""

from __future__ import annotations

from typing import Any

import requests
import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.ui.runtime_data import (
    fetch_index_data,
    fetch_stock_news,
    filter_signals,
    get_market_summary,
    map_cached_signals,
)
from bist_bot.ui.runtime_refresh import sync_runtime_feedback
from bist_bot.ui.runtime_scan import (
    apply_pending_scan_result,
    ensure_initial_data,
    request_scan,
    run_scan,
)
from bist_bot.ui.runtime_styles import inject_styles


def prepare_streamlit_runtime() -> None:
    """Prepare the Streamlit UI by loading data, styles, and refresh state."""
    inject_styles()
    ensure_initial_data()
    apply_pending_scan_result()
    sync_runtime_feedback(run_scan)


def api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = st.session_state.get("auth_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def api_request(method: str, path: str, **kwargs: Any) -> requests.Response:
    headers = kwargs.pop("headers", {})
    merged_headers = {**api_headers(), **headers}
    return requests.request(
        method=method,
        url=f"{settings.API_BASE_URL}{path}",
        headers=merged_headers,
        timeout=kwargs.pop("timeout", settings.API_REQUEST_TIMEOUT_SECONDS),
        **kwargs,
    )


__all__ = [
    "api_headers",
    "api_request",
    "apply_pending_scan_result",
    "ensure_initial_data",
    "fetch_index_data",
    "fetch_stock_news",
    "filter_signals",
    "get_market_summary",
    "inject_styles",
    "map_cached_signals",
    "prepare_streamlit_runtime",
    "request_scan",
    "run_scan",
]
