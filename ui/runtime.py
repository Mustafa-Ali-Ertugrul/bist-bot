"""Compatibility surface for the modular Streamlit runtime helpers."""

from __future__ import annotations

from ui.runtime_data import fetch_index_data, fetch_stock_news, filter_signals, get_market_summary, map_cached_signals
from ui.runtime_refresh import sync_runtime_feedback
from ui.runtime_scan import apply_pending_scan_result, ensure_initial_data, run_scan
from ui.runtime_styles import inject_styles


def prepare_streamlit_runtime() -> None:
    """Prepare the Streamlit UI by loading data, styles, and refresh state."""
    inject_styles()
    ensure_initial_data()
    apply_pending_scan_result()
    sync_runtime_feedback(run_scan)


__all__ = [
    "apply_pending_scan_result",
    "ensure_initial_data",
    "fetch_index_data",
    "fetch_stock_news",
    "filter_signals",
    "get_market_summary",
    "inject_styles",
    "map_cached_signals",
    "prepare_streamlit_runtime",
    "run_scan",
]
