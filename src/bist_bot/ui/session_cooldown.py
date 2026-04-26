"""Session-level cooldown helpers for Streamlit-triggered actions."""

from __future__ import annotations

import time
from typing import Any


def _cooldown_key(action: str) -> str:
    return f"_cooldown_{action}_at"


def cooldown_remaining_seconds(
    state: Any,
    action: str,
    cooldown_seconds: float,
    now: float | None = None,
) -> float:
    current_time = time.time() if now is None else now
    last_triggered_at = float(state.get(_cooldown_key(action), 0.0) or 0.0)
    remaining = cooldown_seconds - (current_time - last_triggered_at)
    return max(0.0, remaining)


def consume_cooldown(
    state: Any,
    action: str,
    cooldown_seconds: float,
    now: float | None = None,
) -> tuple[bool, float]:
    current_time = time.time() if now is None else now
    remaining = cooldown_remaining_seconds(state, action, cooldown_seconds, now=current_time)
    if remaining > 0:
        return False, remaining
    state[_cooldown_key(action)] = current_time
    return True, 0.0
