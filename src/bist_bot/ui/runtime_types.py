"""Shared runtime types for the Streamlit UI flow."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

import pandas as pd

from bist_bot.strategy.signal_models import Signal


class ScanResult(TypedDict):
    all_data: dict[str, pd.DataFrame]
    signals: list[Signal]
    last_scan_time: datetime | None
    error: str | None
