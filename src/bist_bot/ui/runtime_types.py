"""Shared runtime types for the Streamlit UI flow."""

from __future__ import annotations

from datetime import datetime
from typing import NotRequired, TypedDict

import pandas as pd

from bist_bot.strategy.signal_models import Signal


class ScanStats(TypedDict):
    generated: int
    actionable: int
    hold: int


class ScanResult(TypedDict):
    all_data: dict[str, pd.DataFrame]
    signals: list[Signal]
    last_scan_time: datetime | None
    error: str | None
    scan_stats: ScanStats
    rejection_breakdown: NotRequired[dict[str, object]]
    scan_phase: NotRequired[str | None]
