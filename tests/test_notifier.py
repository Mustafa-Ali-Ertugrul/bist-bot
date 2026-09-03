"""Tests for Telegram rate limiter, Retry-After handling, and sell-side labels."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.notifier import (  # noqa: E402
    SlidingWindowRateLimiter,
    TelegramNotifier,
    _backoff_delay,
    _retry_after_seconds,
    send_telegram_with_retry,
)
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402

# ============================================================================
# SlidingWindowRateLimiter
# ============================================================================


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_limiter_allows_upto_limit_without_waiting():
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(limit_per_minute=2, clock=clock, sleep_fn=lambda _: None)

    assert limiter.acquire() == 0.0
    assert limiter.acquire() == 0.0


def test_limiter_blocks_when_window_full():
    clock = _FakeClock()
    waits: list[float] = []

    def _sleep_and_advance(s: float) -> None:
        waits.append(s)
        clock.advance(s)

    limiter = SlidingWindowRateLimiter(
        limit_per_minute=2,
        clock=clock,
        sleep_fn=_sleep_and_advance,
    )

    limiter.acquire()
    limiter.acquire()
    # Third send waits until the oldest entry leaves the 60s window, then proceeds.
    limiter.acquire()

    assert len(waits) == 1
    assert waits[0] == 60.0


def test_limiter_releases_slot_after_window_elapses():
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(limit_per_minute=1, clock=clock, sleep_fn=lambda _: None)

    limiter.acquire()
    assert limiter.wait_time() == 60.0
    clock.advance(60.1)
    assert limiter.wait_time() == 0.0


def test_limiter_config_updates_budget():
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(limit_per_minute=1, clock=clock, sleep_fn=lambda _: None)
    limiter.configure(5)
    assert limiter.limit_per_minute == 5


# ============================================================================
# Retry-After parsing helpers
# ============================================================================


def test_retry_after_parses_header_and_caps():
    resp = SimpleNamespace(headers={"Retry-After": "7"})
    assert _retry_after_seconds(resp) == 7.0


def test_retry_after_is_capped_to_maximum():
    resp = SimpleNamespace(headers={"Retry-After": "500"})
    assert _retry_after_seconds(resp) == 30.0


def test_retry_after_missing_returns_none():
    assert _retry_after_seconds(SimpleNamespace(headers={})) is None


def test_backoff_delay_is_bounded_exponential():
    assert _backoff_delay(0, 5) == 5.0
    assert _backoff_delay(1, 5) == 10.0
    assert _backoff_delay(5, 5) == 30.0  # capped at 30s


# ============================================================================
# send_telegram_with_retry
# ============================================================================


def _make_response(status_code: int, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.raise_for_status.side_effect = (
        requests.exceptions.HTTPError(f"{status_code} error") if status_code >= 400 else None
    )
    return resp


def test_sends_once_on_200(monkeypatch):
    monkeypatch.setattr(
        "bist_bot.notifier.requests.post", MagicMock(return_value=_make_response(200))
    )
    assert send_telegram_with_retry("http://x", "1", "hi") is True


def test_permament_403_dead_letters_and_raises(monkeypatch):
    monkeypatch.setattr(
        "bist_bot.notifier.requests.post", MagicMock(return_value=_make_response(403))
    )
    with pytest.raises(requests.exceptions.HTTPError):
        send_telegram_with_retry("http://x", "1", "hi")


def test_429_respects_retry_after_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("bist_bot.notifier.time.sleep", lambda s: sleeps.append(s))
    responses = [
        _make_response(429, {"Retry-After": "2"}),
        _make_response(200),
    ]
    monkeypatch.setattr("bist_bot.notifier.requests.post", MagicMock(side_effect=responses))

    assert send_telegram_with_retry("http://x", "1", "hi", max_retries=3) is True
    assert sleeps == [2.0]


def test_429_exhaustion_dead_letters_and_returns_false(monkeypatch):
    monkeypatch.setattr("bist_bot.notifier.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "bist_bot.notifier.requests.post",
        MagicMock(return_value=_make_response(429, {"Retry-After": "1"})),
    )

    assert send_telegram_with_retry("http://x", "1", "hi", max_retries=2) is False


def test_transient_error_uses_backoff_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("bist_bot.notifier.time.sleep", lambda s: sleeps.append(s))
    responses = [
        _make_response(503),
        _make_response(200),
    ]
    monkeypatch.setattr("bist_bot.notifier.requests.post", MagicMock(side_effect=responses))

    assert send_telegram_with_retry("http://x", "1", "hi", max_retries=3, retry_delay=5) is True
    assert sleeps[0] > 0


# ============================================================================
# Sell-side labels and diagnosis block
# ============================================================================


def _signal(
    signal_type: SignalType,
    score: float,
    is_actionable: bool,
    buy_threshold: float = 20.0,
    sell_threshold: float = -20.0,
) -> Signal:
    return Signal(
        ticker="THYAO.IS",
        signal_type=signal_type,
        score=score,
        price=100.0,
        timestamp=datetime(2099, 1, 1, 10, 0, 0, tzinfo=UTC),
        is_actionable=is_actionable,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
    )


def test_sell_label_marks_actionable_sell():
    notifier = TelegramNotifier(token="t", chat_id="c")
    label = notifier._signal_label(_signal(SignalType.SELL, -30.0, is_actionable=True))
    assert "SAT SİNYALİ" in label
    assert "actionable" in label


def test_sell_label_marks_non_actionable_as_izleme():
    notifier = TelegramNotifier(token="t", chat_id="c")
    label = notifier._signal_label(_signal(SignalType.SELL, -10.0, is_actionable=False))
    assert "actionable DEĞİL" in label


def test_buy_label_marks_actionable_buy():
    notifier = TelegramNotifier(token="t", chat_id="c")
    label = notifier._signal_label(_signal(SignalType.BUY, 30.0, is_actionable=True))
    assert "AL SİNYALİ" in label


def test_diagnosis_uses_sell_threshold_for_sell_signals():
    notifier = TelegramNotifier(token="t", chat_id="c")
    msg = notifier._build_diagnosis_block(_signal(SignalType.SELL, -30.0, is_actionable=True))
    assert "SAT eşik -20" in msg
    assert "actionable" in msg


def test_diagnosis_uses_buy_threshold_for_buy_signals():
    notifier = TelegramNotifier(token="t", chat_id="c")
    msg = notifier._build_diagnosis_block(_signal(SignalType.BUY, 30.0, is_actionable=True))
    assert "AL eşik 20" in msg


def test_scan_summary_marks_actionable_sell():
    notifier = TelegramNotifier(token="t", chat_id="c")
    captured: list[str] = []

    def _capture(base_url: object, chat_id: object, text: str, **kw: object) -> bool:
        captured.append(text)
        return True

    notifier.sender = _capture
    actionable_sell = _signal(SignalType.SELL, -30.0, is_actionable=True)
    notifier.send_scan_summary([actionable_sell], total_scanned=1)
    assert "— SAT (actionable)" in captured[0]
