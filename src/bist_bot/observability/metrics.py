"""Prometheus-compatible metrics for live trading observability.

Metrics (task contract):
- bist_bot_signals_total{signal_type}
- bist_bot_orders_total{side,status}
- bist_bot_positions_current
- bist_bot_pnl_daily
- bist_bot_order_latency_seconds

Works with or without ``prometheus_client`` installed (in-memory fallback).
"""

from __future__ import annotations

import importlib
import threading
from collections import defaultdict
from typing import Any

try:  # pragma: no cover - optional dependency
    _prom: Any = importlib.import_module("prometheus_client")
except ImportError:  # pragma: no cover
    _prom = None


class _ObservabilityMetrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._init()

    def _init(self) -> None:
        self._signals: dict[str, float] = defaultdict(float)
        self._orders: dict[tuple[str, str], float] = defaultdict(float)
        self._positions_current = 0.0
        self._pnl_daily = 0.0
        self._latency_sum = 0.0
        self._latency_count = 0.0
        self._latency_buckets: dict[float, float] = {
            0.05: 0.0,
            0.1: 0.0,
            0.25: 0.0,
            0.5: 0.0,
            1.0: 0.0,
            2.5: 0.0,
            5.0: 0.0,
            10.0: 0.0,
        }
        self._prom_registry: Any | None = None
        self._prom_signals: Any | None = None
        self._prom_orders: Any | None = None
        self._prom_positions: Any | None = None
        self._prom_pnl: Any | None = None
        self._prom_latency: Any | None = None
        if _prom is None:
            return
        registry = _prom.CollectorRegistry()
        self._prom_registry = registry
        self._prom_signals = _prom.Counter(
            "bist_bot_signals_total",
            "Total strategy signals emitted",
            ["signal_type"],
            registry=registry,
        )
        self._prom_orders = _prom.Counter(
            "bist_bot_orders_total",
            "Total broker order submissions",
            ["side", "status"],
            registry=registry,
        )
        self._prom_positions = _prom.Gauge(
            "bist_bot_positions_current",
            "Current open position count",
            registry=registry,
        )
        self._prom_pnl = _prom.Gauge(
            "bist_bot_pnl_daily",
            "Daily realised PnL",
            registry=registry,
        )
        self._prom_latency = _prom.Histogram(
            "bist_bot_order_latency_seconds",
            "Broker order submission latency in seconds",
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
            registry=registry,
        )

    def reset(self) -> None:
        with self._lock:
            self._init()

    def record_signal(self, signal_type: str, amount: float = 1.0) -> None:
        label = str(signal_type or "UNKNOWN")
        with self._lock:
            self._signals[label] += amount
            if self._prom_signals is not None:
                self._prom_signals.labels(signal_type=label).inc(amount)

    def record_order(self, side: str, status: str, amount: float = 1.0) -> None:
        side_label = str(side or "UNKNOWN").upper()
        status_label = str(status or "UNKNOWN").upper()
        with self._lock:
            self._orders[(side_label, status_label)] += amount
            if self._prom_orders is not None:
                self._prom_orders.labels(side=side_label, status=status_label).inc(amount)

    def set_positions_current(self, value: float) -> None:
        numeric = float(value)
        with self._lock:
            self._positions_current = numeric
            if self._prom_positions is not None:
                self._prom_positions.set(numeric)

    def set_daily_pnl(self, value: float) -> None:
        numeric = float(value)
        with self._lock:
            self._pnl_daily = numeric
            if self._prom_pnl is not None:
                self._prom_pnl.set(numeric)

    def observe_order_latency(self, seconds: float) -> None:
        latency = max(float(seconds), 0.0)
        with self._lock:
            self._latency_sum += latency
            self._latency_count += 1.0
            for bound in self._latency_buckets:
                if latency <= bound:
                    self._latency_buckets[bound] += 1.0
            if self._prom_latency is not None:
                self._prom_latency.observe(latency)

    def render(self) -> str:
        with self._lock:
            if self._prom_registry is not None and _prom is not None:
                return _prom.generate_latest(self._prom_registry).decode("utf-8")
            lines: list[str] = []
            lines.append("# TYPE bist_bot_signals_total counter")
            for signal_type, value in sorted(self._signals.items()):
                lines.append(f'bist_bot_signals_total{{signal_type="{signal_type}"}} {value}')
            if not self._signals:
                lines.append('bist_bot_signals_total{signal_type="NONE"} 0.0')
            lines.append("# TYPE bist_bot_orders_total counter")
            for (side, status), value in sorted(self._orders.items()):
                lines.append(f'bist_bot_orders_total{{side="{side}",status="{status}"}} {value}')
            if not self._orders:
                lines.append('bist_bot_orders_total{side="NONE",status="NONE"} 0.0')
            lines.append("# TYPE bist_bot_positions_current gauge")
            lines.append(f"bist_bot_positions_current {self._positions_current}")
            lines.append("# TYPE bist_bot_pnl_daily gauge")
            lines.append(f"bist_bot_pnl_daily {self._pnl_daily}")
            lines.append("# TYPE bist_bot_order_latency_seconds histogram")
            cumulative = 0.0
            for bound in sorted(self._latency_buckets):
                cumulative += self._latency_buckets[bound]
                lines.append(f'bist_bot_order_latency_seconds_bucket{{le="{bound}"}} {cumulative}')
            lines.append(
                f'bist_bot_order_latency_seconds_bucket{{le="+Inf"}} {self._latency_count}'
            )
            lines.append(f"bist_bot_order_latency_seconds_sum {self._latency_sum}")
            lines.append(f"bist_bot_order_latency_seconds_count {self._latency_count}")
            return "\n".join(lines) + "\n"


_REGISTRY = _ObservabilityMetrics()


def reset_observability_metrics() -> None:
    _REGISTRY.reset()


def record_signal(signal_type: str, amount: float = 1.0) -> None:
    _REGISTRY.record_signal(signal_type, amount)


def record_order(side: str, status: str, amount: float = 1.0) -> None:
    _REGISTRY.record_order(side, status, amount)


def set_positions_current(value: float) -> None:
    _REGISTRY.set_positions_current(value)


def set_daily_pnl(value: float) -> None:
    _REGISTRY.set_daily_pnl(value)


def observe_order_latency(seconds: float) -> None:
    _REGISTRY.observe_order_latency(seconds)


def render_observability_metrics() -> str:
    return _REGISTRY.render()


__all__ = [
    "observe_order_latency",
    "record_order",
    "record_signal",
    "render_observability_metrics",
    "reset_observability_metrics",
    "set_daily_pnl",
    "set_positions_current",
]
