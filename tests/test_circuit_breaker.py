"""Tests for the circuit breaker safety mechanism."""

from __future__ import annotations

import threading
import time

from bist_bot.risk.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)


def _make_breaker(
    capital: float = 10_000.0,
    daily_loss_limit_pct: float = 3.0,
    max_consecutive_errors: int = 3,
    cooldown_seconds: float = 0.1,
    half_open_max_probes: int = 1,
    max_account_drawdown_pct: float = 1.0,
) -> CircuitBreaker:
    return CircuitBreaker(
        capital=capital,
        config=CircuitBreakerConfig(
            daily_loss_limit_pct=daily_loss_limit_pct,
            max_consecutive_errors=max_consecutive_errors,
            cooldown_seconds=cooldown_seconds,
            half_open_max_probes=half_open_max_probes,
            max_account_drawdown_pct=max_account_drawdown_pct,
        ),
    )


# ── State machine basics ───────────────────────────────────────────


def test_initial_state_is_closed() -> None:
    breaker = _make_breaker()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow_request() is True


def test_daily_loss_trips_breaker() -> None:
    breaker = _make_breaker(capital=10_000, daily_loss_limit_pct=3.0)

    breaker.record_loss(299.0)
    assert breaker.state == CircuitState.CLOSED

    breaker.record_loss(1.0)  # total = 300 → exactly 3%
    assert breaker.state == CircuitState.OPEN
    assert breaker.allow_request() is False


def test_consecutive_errors_trip_breaker() -> None:
    breaker = _make_breaker(max_consecutive_errors=3)

    breaker.record_error()
    breaker.record_error()
    assert breaker.state == CircuitState.CLOSED

    breaker.record_error()  # 3rd
    assert breaker.state == CircuitState.OPEN


def test_success_resets_error_counter() -> None:
    breaker = _make_breaker(max_consecutive_errors=3)

    breaker.record_error()
    breaker.record_error()
    breaker.record_success()  # resets
    breaker.record_error()
    breaker.record_error()
    assert breaker.state == CircuitState.CLOSED  # only 2 consecutive


# ── OPEN → HALF_OPEN → CLOSED transition ───────────────────────────


def test_cooldown_transitions_to_half_open() -> None:
    breaker = _make_breaker(max_consecutive_errors=1, cooldown_seconds=0.05)

    breaker.record_error()
    assert breaker.state == CircuitState.OPEN

    time.sleep(0.1)
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.allow_request() is True  # probe allowed


def test_half_open_success_closes_breaker() -> None:
    breaker = _make_breaker(max_consecutive_errors=1, cooldown_seconds=0.01)

    breaker.record_error()
    time.sleep(0.05)
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_half_open_error_reopens_breaker() -> None:
    breaker = _make_breaker(max_consecutive_errors=1, cooldown_seconds=0.01)

    breaker.record_error()
    time.sleep(0.05)
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_error()
    assert breaker.state == CircuitState.OPEN


# ── Daily rollover ──────────────────────────────────────────────────


def test_daily_loss_resets_on_new_day() -> None:
    breaker = _make_breaker(capital=10_000, daily_loss_limit_pct=3.0)

    breaker.record_loss(200.0)
    assert breaker.state == CircuitState.CLOSED

    # Simulate date change
    breaker._daily_loss_date = "1999-01-01"
    breaker.record_loss(100.0)  # new day → accumulated = 100 only
    assert breaker.state == CircuitState.CLOSED
    assert breaker._daily_loss == 100.0


# ── Manual reset ────────────────────────────────────────────────────


def test_reset_closes_breaker_and_clears_counters() -> None:
    breaker = _make_breaker(max_consecutive_errors=1)

    breaker.record_error()
    assert breaker.state == CircuitState.OPEN

    breaker.reset()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow_request() is True


# ── Snapshot ────────────────────────────────────────────────────────


def test_snapshot_returns_expected_keys() -> None:
    breaker = _make_breaker()
    snap = breaker.snapshot()

    assert "state" in snap
    assert "daily_loss" in snap
    assert "daily_loss_pct" in snap
    assert "consecutive_errors" in snap
    assert snap["state"] == "CLOSED"


# ── Thread safety ───────────────────────────────────────────────────


def test_concurrent_access_does_not_corrupt_state() -> None:
    breaker = _make_breaker(
        capital=100_000,
        daily_loss_limit_pct=50.0,
        max_consecutive_errors=1000,
    )
    errors: list[Exception] = []

    def worker(fn, count: int) -> None:
        try:
            for _ in range(count):
                fn()
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(lambda: breaker.record_loss(0.01), 200)),
        threading.Thread(target=worker, args=(breaker.record_error, 200)),
        threading.Thread(target=worker, args=(breaker.record_success, 200)),
        threading.Thread(target=worker, args=(breaker.allow_request, 200)),
        threading.Thread(target=worker, args=(breaker.snapshot, 200)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []


# ── Edge cases ──────────────────────────────────────────────────────


def test_zero_capital_raises_value_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="capital must be positive"):
        CircuitBreaker(capital=0)


def test_negative_capital_raises_value_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="capital must be positive"):
        CircuitBreaker(capital=-1000)


# ── Drawdown tracking (Item 5 extension) ─────────────────────────────


def test_drawdown_accumulates_and_trips_at_threshold() -> None:
    breaker = _make_breaker(
        capital=10_000.0,
        max_account_drawdown_pct=0.10,  # 10 % threshold
    )
    # Simulate a 5 % drop → no trip.
    breaker.record_equity_change(-500.0)
    assert breaker.state == CircuitState.CLOSED
    assert round(breaker.current_drawdown_pct, 4) == 0.05

    # Another 5 % drop → total 10 %, should trip.
    breaker.record_equity_change(-500.0)
    assert breaker.state == CircuitState.OPEN


def test_peak_equity_tracks_upward_only() -> None:
    breaker = _make_breaker(capital=10_000.0, max_account_drawdown_pct=1.0)
    breaker.record_equity_change(2000.0)  # peak rises to 12_000
    assert breaker.current_drawdown_pct == 0.0
    breaker.record_equity_change(-3000.0)  # equity 9_000, dd = 3000/12000 = 25%
    assert round(breaker.current_drawdown_pct, 4) == 0.25


def test_reset_clears_drawdown_state() -> None:
    breaker = _make_breaker(
        capital=10_000.0,
        max_account_drawdown_pct=1.0,
    )
    breaker.record_equity_change(-500.0)
    assert breaker.current_drawdown_pct > 0
    breaker.reset()
    assert breaker.current_drawdown_pct == 0.0


def test_snapshot_includes_drawdown_when_nonzero() -> None:
    breaker = _make_breaker(capital=10_000.0, max_account_drawdown_pct=1.0)
    snap = breaker.snapshot()
    assert "drawdown_pct" not in snap  # no loss yet

    breaker.record_equity_change(-500.0)
    snap = breaker.snapshot()
    assert "drawdown_pct" in snap
    assert snap["drawdown_pct"] > 0


# ── VaR estimation ───────────────────────────────────────────────────


def test_var_returns_zero_with_insufficient_history() -> None:
    breaker = _make_breaker(capital=10_000.0)
    assert breaker.estimate_var() == 0.0


def test_var_returns_nonzero_after_enough_data() -> None:
    breaker = _make_breaker(capital=10_000.0)
    # Feed 15 daily PnL values with negative mean.
    pnl_values = [-100.0] * 15
    for pnl in pnl_values:
        breaker.record_equity_change(pnl)
    var = breaker.estimate_var(confidence=0.95)
    assert var > 0.0
