"""Thread-safe metrics registry with optional prometheus_client support."""

from __future__ import annotations

import threading
from collections import OrderedDict

try:  # pragma: no cover - exercised indirectly depending on environment
    from prometheus_client import (  # type: ignore[import-not-found]
        CollectorRegistry,
        Counter,
        Gauge,
        generate_latest,
    )
except ImportError:  # pragma: no cover - fallback remains covered
    CollectorRegistry = None
    Counter = None
    Gauge = None
    generate_latest = None


_COUNTER_DEFAULTS = OrderedDict(
    {
        "bist_scan_total": 0.0,
        "bist_scan_fail_total": 0.0,
        "bist_signal_emitted_total": 0.0,
        "bist_auto_execute_total": 0.0,
        "bist_auto_execute_fail_total": 0.0,
    }
)

_GAUGE_DEFAULTS = OrderedDict(
    {
        "bist_last_scan_duration_ms": 0.0,
        "bist_last_scan_scanned_count": 0.0,
    }
)


class _MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._init_registry()

    def _init_registry(self) -> None:
        self._counters = OrderedDict(
            (name, float(value)) for name, value in _COUNTER_DEFAULTS.items()
        )
        self._gauges = OrderedDict((name, float(value)) for name, value in _GAUGE_DEFAULTS.items())
        self._prom_registry = None
        self._prom_counters = {}
        self._prom_gauges = {}
        if CollectorRegistry is None or Counter is None or Gauge is None:
            return
        registry = CollectorRegistry()
        self._prom_registry = registry
        self._prom_counters = {
            name: Counter(name, name.replace("_", " "), registry=registry)
            for name in _COUNTER_DEFAULTS
        }
        self._prom_gauges = {
            name: Gauge(name, name.replace("_", " "), registry=registry) for name in _GAUGE_DEFAULTS
        }

    def reset(self) -> None:
        with self._lock:
            self._init_registry()

    def inc_counter(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + amount
            counter = self._prom_counters.get(name)
            if counter is not None:
                counter.inc(amount)

    def set_gauge(self, name: str, value: float) -> None:
        numeric_value = float(value)
        with self._lock:
            self._gauges[name] = numeric_value
            gauge = self._prom_gauges.get(name)
            if gauge is not None:
                gauge.set(numeric_value)

    def render(self) -> str:
        with self._lock:
            if self._prom_registry is not None and generate_latest is not None:
                return generate_latest(self._prom_registry).decode("utf-8")
            lines: list[str] = []
            for name, value in self._counters.items():
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
            for name, value in self._gauges.items():
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
            return "\n".join(lines) + "\n"


_REGISTRY = _MetricsRegistry()


def reset_metrics() -> None:
    _REGISTRY.reset()


def inc_counter(name: str, amount: float = 1.0) -> None:
    _REGISTRY.inc_counter(name, amount)


def set_gauge(name: str, value: float) -> None:
    _REGISTRY.set_gauge(name, value)


def render_metrics() -> str:
    return _REGISTRY.render()
