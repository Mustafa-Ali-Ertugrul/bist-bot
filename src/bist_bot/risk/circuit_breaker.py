"""Circuit breaker that halts trading when risk thresholds are breached.

The breaker monitors two independent failure signals:

1. **Daily realised loss** – When cumulative intraday losses exceed a
   configurable percentage of capital the breaker trips to ``OPEN``.
2. **Consecutive scan/order errors** – Repeated infrastructure failures
   (API timeouts, broker rejections) also trip the breaker.

State machine::

    CLOSED ──(threshold breached)──▸ OPEN
    OPEN   ──(cooldown expires)────▸ HALF_OPEN
    HALF_OPEN ──(success)──────────▸ CLOSED
    HALF_OPEN ──(failure)──────────▸ OPEN
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from bist_bot.app_logging import get_logger

logger = get_logger(__name__, component="circuit_breaker")


class CircuitState(StrEnum):
    """Operational state of the circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    """Tuneable thresholds — all values have safe defaults."""

    daily_loss_limit_pct: float = 3.0
    """Maximum daily loss as a percentage of capital before tripping."""

    max_consecutive_errors: int = 3
    """Number of consecutive errors before tripping."""

    cooldown_seconds: float = 300.0
    """Seconds to wait in OPEN state before transitioning to HALF_OPEN."""

    half_open_max_probes: int = 1
    """Successful probes required in HALF_OPEN to transition to CLOSED."""

    max_account_drawdown_pct: float = 0.15
    """Max peak-to-trough drawdown as a fraction of peak capital before trip."""

    var_confidence_level: float = 0.95
    """Confidence level for VaR estimation (default 95 %)."""

    var_lookback_bars: int = 60
    """Number of daily PnL bars used for VaR estimation."""


class CircuitBreaker:
    """Thread-safe circuit breaker for live trading protection.

    Usage::

        breaker = CircuitBreaker(capital=10_000)

        if not breaker.allow_request():
            logger.warning("circuit_open – trading halted")
            return

        try:
            result = execute_trade(...)
            breaker.record_success()
            if result.pnl < 0:
                breaker.record_loss(abs(result.pnl))
        except Exception:
            breaker.record_error()
    """

    def __init__(
        self,
        capital: float,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        if capital <= 0:
            raise ValueError("capital must be positive")
        self._capital = capital
        self._config = config or CircuitBreakerConfig()
        self._lock = threading.Lock()

        # Mutable state
        self._state = CircuitState.CLOSED
        self._daily_loss = 0.0
        self._daily_loss_date: str = self._today()
        self._consecutive_errors = 0
        self._opened_at: float = 0.0
        self._half_open_successes = 0

        # Drawdown tracking (Item 5 — portfolio breaker extension)
        self._peak_equity: float = capital
        self._daily_pnl_series: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition()
            return self._state

    def allow_request(self) -> bool:
        """Return ``True`` if trading is permitted under current state."""
        with self._lock:
            self._maybe_transition()
            if self._state == CircuitState.CLOSED:
                return True
            return self._state == CircuitState.HALF_OPEN  # allow probe

    def record_loss(self, amount: float) -> None:
        """Register a realised loss (positive number)."""
        with self._lock:
            self._roll_daily_if_needed()
            self._daily_loss += abs(amount)
            loss_pct = (self._daily_loss / self._capital) * 100.0
            if loss_pct >= self._config.daily_loss_limit_pct:
                self._trip(f"daily loss {loss_pct:.2f}% >= {self._config.daily_loss_limit_pct}%")
                return

            # Track equity for drawdown detection
            self._update_equity(-amount)

    def record_error(self) -> None:
        """Register a scan or execution error."""
        with self._lock:
            self._consecutive_errors += 1
            if self._state == CircuitState.HALF_OPEN:
                self._trip("error during HALF_OPEN probe")
                return
            if self._consecutive_errors >= self._config.max_consecutive_errors:
                self._trip(
                    f"{self._consecutive_errors} consecutive errors "
                    f">= {self._config.max_consecutive_errors}"
                )

    def record_success(self) -> None:
        """Register a successful operation (resets error counter)."""
        with self._lock:
            self._consecutive_errors = 0
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._config.half_open_max_probes:
                    self._close()

    def reset(self) -> None:
        """Force-reset the breaker to CLOSED (manual override)."""
        with self._lock:
            self._close()
            self._daily_loss = 0.0
            self._consecutive_errors = 0
            self._peak_equity = self._capital
            self._daily_pnl_series.clear()

    def record_equity_change(self, pnl: float) -> None:
        """Register a daily PnL delta for drawdown/VaR tracking."""
        with self._lock:
            self._update_equity(pnl)

    @property
    def current_drawdown_pct(self) -> float:
        """Current peak-to-trough drawdown as a positive fraction."""
        with self._lock:
            if self._peak_equity <= 0:
                return 0.0
            equity = self._capital
            dd = (self._peak_equity - equity) / self._peak_equity
            return max(0.0, dd)

    def estimate_var(self, confidence: float | None = None) -> float:
        """Parametric (z-score) VaR over the lookback window.

        Returns the VaR as a positive fraction of capital. Returns 0.0 when
        there is insufficient history.
        """
        with self._lock:
            conf = confidence or self._config.var_confidence_level
            series = list(self._daily_pnl_series[-self._config.var_lookback_bars:])
            if len(series) < 10:
                return 0.0
            import statistics

            mean = statistics.mean(series)
            stdev = statistics.pstdev(series) if len(series) > 1 else 0.0
            # z-score approximation for the given confidence level.
            z_scores: dict[float, float] = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
            z = z_scores.get(conf, 1.645)
            var = -(mean - z * stdev)
            return max(0.0, var / self._capital)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable status snapshot."""
        with self._lock:
            self._maybe_transition()
            # Compute drawdown / VaR inline to avoid re-acquiring the lock.
            dd_pct = 0.0
            if self._peak_equity > 0:
                dd_pct = max(0.0, (self._peak_equity - self._capital) / self._peak_equity)
            var_val = 0.0
            series = list(self._daily_pnl_series[-self._config.var_lookback_bars:])
            if len(series) >= 10 and self._capital > 0:
                import statistics
                mean = statistics.mean(series)
                stdev = statistics.pstdev(series) if len(series) > 1 else 0.0
                z_scores = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
                z = z_scores.get(self._config.var_confidence_level, 1.645)
                var_val = max(0.0, -(mean - z * stdev) / self._capital)

            result: dict[str, Any] = {
                "state": str(self._state),
                "daily_loss": round(self._daily_loss, 2),
                "daily_loss_pct": round((self._daily_loss / self._capital) * 100, 2),
                "daily_loss_limit_pct": self._config.daily_loss_limit_pct,
                "consecutive_errors": self._consecutive_errors,
                "max_consecutive_errors": self._config.max_consecutive_errors,
                "cooldown_seconds": self._config.cooldown_seconds,
            }
            if dd_pct > 0:
                result["drawdown_pct"] = round(dd_pct * 100, 2)
                result["max_drawdown_limit_pct"] = (
                    self._config.max_account_drawdown_pct * 100
                )
            if var_val > 0:
                result["var_95_pct"] = round(var_val * 100, 2)
            return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trip(self, reason: str) -> None:
        """Transition to OPEN (caller must hold ``_lock``)."""
        prev = self._state
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._half_open_successes = 0
        logger.warning(
            "circuit_breaker_tripped",
            previous_state=str(prev),
            reason=reason,
            daily_loss=round(self._daily_loss, 2),
            consecutive_errors=self._consecutive_errors,
        )
        try:
            from bist_bot.observability.alerts import AlertLevel, send_alert
            from bist_bot.observability.metrics import set_daily_pnl

            # daily_loss is positive magnitude of losses; expose as negative PnL.
            set_daily_pnl(-float(self._daily_loss))
            send_alert(
                "Circuit breaker tripped",
                reason,
                level=AlertLevel.CRITICAL,
                error=reason,
                daily_loss=round(self._daily_loss, 2),
                consecutive_errors=self._consecutive_errors,
            )
        except Exception:
            pass

    def _close(self) -> None:
        """Transition to CLOSED (caller must hold ``_lock``)."""
        prev = self._state
        self._state = CircuitState.CLOSED
        self._half_open_successes = 0
        self._consecutive_errors = 0
        if prev != CircuitState.CLOSED:
            logger.info(
                "circuit_breaker_closed",
                previous_state=str(prev),
            )

    def _maybe_transition(self) -> None:
        """Auto-transition OPEN → HALF_OPEN after cooldown (caller holds ``_lock``)."""
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._config.cooldown_seconds:
            self._state = CircuitState.HALF_OPEN
            self._half_open_successes = 0
            logger.info(
                "circuit_breaker_half_open",
                elapsed_seconds=round(elapsed, 1),
            )

    def _roll_daily_if_needed(self) -> None:
        """Reset daily loss accumulator at date boundary."""
        today = self._today()
        if today != self._daily_loss_date:
            self._daily_loss = 0.0
            self._daily_loss_date = today
            # Roll the PnL series to the new day.
            self._daily_pnl_series.clear()

    def _update_equity(self, pnl_delta: float) -> None:
        """Update tracked equity and check drawdown threshold (caller holds lock)."""
        self._capital += pnl_delta
        if self._capital > self._peak_equity:
            self._peak_equity = self._capital
        dd_pct = (self._peak_equity - self._capital) / self._peak_equity if self._peak_equity > 0 else 0.0
        if dd_pct >= self._config.max_account_drawdown_pct:
            self._trip(f"drawdown {dd_pct:.2%} >= {self._config.max_account_drawdown_pct:.2%}")
        self._daily_pnl_series.append(float(pnl_delta))

    @staticmethod
    def _today() -> str:
        from datetime import datetime, timedelta, timezone

        tr = timezone(timedelta(hours=3))
        return datetime.now(tr).strftime("%Y-%m-%d")
