from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from bist_bot.app_metrics import inc_counter, render_metrics, reset_metrics, set_gauge


def test_render_metrics_contains_counter_and_gauge_values() -> None:
    reset_metrics()

    inc_counter("bist_scan_total")
    inc_counter("bist_signal_emitted_total", 3)
    set_gauge("bist_last_scan_duration_ms", 42.5)

    rendered = render_metrics()

    assert "bist_scan_total" in rendered
    assert "bist_signal_emitted_total" in rendered
    assert "bist_last_scan_duration_ms 42.5" in rendered


def test_counter_updates_are_thread_safe() -> None:
    reset_metrics()

    def _increment_many() -> None:
        for _ in range(250):
            inc_counter("bist_scan_total")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_increment_many) for _ in range(8)]
        for future in futures:
            future.result()

    rendered = render_metrics()

    assert "bist_scan_total 2000.0" in rendered or "bist_scan_total 2000" in rendered
