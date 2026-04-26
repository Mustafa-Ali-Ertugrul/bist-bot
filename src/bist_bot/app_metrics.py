"""Thread-safe metrics registry with optional prometheus_client support."""

from __future__ import annotations

import importlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, cast

try:  # pragma: no cover - exercised indirectly depending on environment
    _prometheus_client: Any = importlib.import_module("prometheus_client")
except ImportError:  # pragma: no cover - fallback remains covered
    _prometheus_client = None


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
        self._prom_registry: Any | None = None
        self._prom_counters: dict[str, Any] = {}
        self._prom_gauges: dict[str, Any] = {}
        collector_registry = getattr(_prometheus_client, "CollectorRegistry", None)
        counter_cls = getattr(_prometheus_client, "Counter", None)
        gauge_cls = getattr(_prometheus_client, "Gauge", None)
        if collector_registry is None or counter_cls is None or gauge_cls is None:
            return
        registry = collector_registry()
        self._prom_registry = registry
        self._prom_counters = {
            name: counter_cls(name, name.replace("_", " "), registry=registry)
            for name in _COUNTER_DEFAULTS
        }
        self._prom_gauges = {
            name: gauge_cls(name, name.replace("_", " "), registry=registry)
            for name in _GAUGE_DEFAULTS
        }

    def reset(self) -> None:
        with self._lock:
            self._init_registry()

    def _ensure_prom_counter(self, name: str) -> Any | None:
        counter_cls = getattr(_prometheus_client, "Counter", None)
        if self._prom_registry is None or counter_cls is None:
            return None
        counter = self._prom_counters.get(name)
        if counter is None:
            counter = counter_cls(name, name.replace("_", " "), registry=self._prom_registry)
            self._prom_counters[name] = counter
        return counter

    def _ensure_prom_gauge(self, name: str) -> Any | None:
        gauge_cls = getattr(_prometheus_client, "Gauge", None)
        if self._prom_registry is None or gauge_cls is None:
            return None
        gauge = self._prom_gauges.get(name)
        if gauge is None:
            gauge = gauge_cls(name, name.replace("_", " "), registry=self._prom_registry)
            self._prom_gauges[name] = gauge
        return gauge

    def inc_counter(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + amount
            counter = self._ensure_prom_counter(name)
            if counter is not None:
                counter.inc(amount)

    def set_gauge(self, name: str, value: float) -> None:
        numeric_value = float(value)
        with self._lock:
            self._gauges[name] = numeric_value
            gauge = self._ensure_prom_gauge(name)
            if gauge is not None:
                gauge.set(numeric_value)

    def render(self) -> str:
        with self._lock:
            prom_registry = self._prom_registry
            counter_snapshot = list(self._counters.items())
            gauge_snapshot = list(self._gauges.items())
        generate_latest = getattr(_prometheus_client, "generate_latest", None)
        if prom_registry is not None and generate_latest is not None:
            renderer = cast(Callable[[Any], bytes], generate_latest)
            return str(renderer(prom_registry).decode("utf-8"))
        lines: list[str] = []
        for name, value in counter_snapshot:
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        for name, value in gauge_snapshot:
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
