from __future__ import annotations

from bist_bot.app_metrics import render_metrics, reset_metrics
from bist_bot.config.settings import settings
from bist_bot.dependencies import _report_auto_execute_migration_state


def test_legacy_auto_execute_without_new_gate_warns_and_sets_metric(caplog) -> None:
    reset_metrics()
    with settings.override(AUTO_EXECUTE=True, AUTO_EXECUTE_ENABLED=False):
        blocked = _report_auto_execute_migration_state()

    assert blocked is True
    assert "auto_execute_disabled_new_gate_required" in caplog.text
    assert "bist_auto_execute_migration_blocked 1.0" in render_metrics()


def test_explicit_new_gate_clears_migration_metric() -> None:
    reset_metrics()
    with settings.override(AUTO_EXECUTE=True, AUTO_EXECUTE_ENABLED=True):
        blocked = _report_auto_execute_migration_state()

    assert blocked is False
    assert "bist_auto_execute_migration_blocked 0.0" in render_metrics()
