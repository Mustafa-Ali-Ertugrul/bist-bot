"""Post-scan refresh helpers for the Streamlit runtime."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import cast

import streamlit as st

TR = timezone(timedelta(hours=3))


def sync_runtime_feedback(run_scan_callback) -> None:
    """Handle refresh timers, pending background state, and user feedback."""
    if st.session_state.get("scan_error"):
        st.error(f"Arka plan taramasi hatasi: {st.session_state.scan_error}")

    if _should_auto_refresh():
        run_scan_callback()
        st.rerun()

    if st.session_state.get("scan_in_progress"):
        if st.session_state.get("just_logged_in"):
            return
        st.caption("Arka planda guncel tarama suruyor; sonuc hazir oldugunda ekran yenilenir.")
        time.sleep(1)
        st.rerun()


def _should_auto_refresh() -> bool:
    last_scan_time = cast(datetime | None, st.session_state.get("last_scan_time"))
    if not st.session_state.get("auto_refresh") or last_scan_time is None:
        return False

    elapsed = (datetime.now(TR) - last_scan_time).total_seconds()
    refresh_interval = float(st.session_state.get("refresh_interval", 5) or 5)
    return elapsed >= refresh_interval * 60
