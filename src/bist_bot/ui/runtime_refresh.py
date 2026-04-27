from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import streamlit as st

TR = timezone(timedelta(hours=3))


def sync_runtime_feedback(run_scan_callback) -> None:
    if st.session_state.get("scan_error"):
        st.error(f"Arka plan taramasi hatasi: {st.session_state.scan_error}")

    if _should_auto_refresh():
        run_scan_callback()

    if st.session_state.get("scan_in_progress"):
        st.info("Arka planda tarama suruyor...", icon="⏳")


def _should_auto_refresh() -> bool:
    last_scan_time = cast(datetime | None, st.session_state.get("last_scan_time"))
    if not st.session_state.get("auto_refresh") or last_scan_time is None:
        return False

    elapsed = (datetime.now(TR) - last_scan_time).total_seconds()
    refresh_interval = float(st.session_state.get("refresh_interval", 5) or 5)
    return elapsed >= refresh_interval * 60
