"""Minimal in-memory Prometheus-style metrics registry."""

from __future__ import annotations

from collections import OrderedDict


_COUNTERS = OrderedDict(
    {
        "bist_scan_total": 0.0,
        "bist_scan_fail_total": 0.0,
        "bist_signal_emitted_total": 0.0,
        "bist_auto_execute_total": 0.0,
        "bist_auto_execute_fail_total": 0.0,
    }
)

_GAUGES = OrderedDict(
    {
        "bist_last_scan_duration_ms": 0.0,
        "bist_last_scan_scanned_count": 0.0,
    }
)


def reset_metrics() -> None:
    for key in _COUNTERS:
        _COUNTERS[key] = 0.0
    for key in _GAUGES:
        _GAUGES[key] = 0.0


def inc_counter(name: str, amount: float = 1.0) -> None:
    _COUNTERS[name] = _COUNTERS.get(name, 0.0) + amount


def set_gauge(name: str, value: float) -> None:
    _GAUGES[name] = float(value)


def render_metrics() -> str:
    lines: list[str] = []
    for name, value in _COUNTERS.items():
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")
    for name, value in _GAUGES.items():
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"
