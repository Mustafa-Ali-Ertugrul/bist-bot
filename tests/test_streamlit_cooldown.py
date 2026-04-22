"""Tests for Streamlit session cooldown helper."""

from __future__ import annotations

from bist_bot.ui.session_cooldown import consume_cooldown, cooldown_remaining_seconds


def test_consume_cooldown_allows_first_request() -> None:
    state: dict[str, float] = {}

    allowed, remaining = consume_cooldown(state, action="scan", cooldown_seconds=5.0, now=100.0)

    assert allowed is True
    assert remaining == 0.0


def test_consume_cooldown_blocks_rapid_repeat_request() -> None:
    state: dict[str, float] = {}
    consume_cooldown(state, action="analyze", cooldown_seconds=4.0, now=100.0)

    allowed, remaining = consume_cooldown(state, action="analyze", cooldown_seconds=4.0, now=102.5)

    assert allowed is False
    assert 1.4 < remaining < 1.6


def test_cooldown_expires_after_interval() -> None:
    state: dict[str, float] = {"_cooldown_scan_at": 100.0}

    remaining = cooldown_remaining_seconds(state, action="scan", cooldown_seconds=3.0, now=104.0)

    assert remaining == 0.0
