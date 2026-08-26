import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def _freeze_market_hours_off(monkeypatch):
    """Keep scan orchestration tests independent of wall-clock market hours (B4).

    The freshness gate (``ScanService._apply_freshness_gate``) activates only
    while BIST is open; with its stale test fixtures that aborts scans. The
    gate's own behaviour is covered by ``tests/test_freshness_gate.py``, which
    re-patches ``bist_bot.scanner.is_bist_open`` to ``lambda: True`` per test.
    Other modules (scheduler, worker_http, market_calendar) import their own
    reference, so only the scanner module's name is patched here (call via
    ``import bist_bot.scanner as scanner_module`` — patch-where-used rule).
    """
    import bist_bot.scanner as scanner_module

    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: False)


@pytest.fixture(autouse=True)
def _stub_default_outcome_tracker(monkeypatch):
    """Keep ScanService's default SignalOutcomeTracker out of the real results/ dir.

    ScanService builds ``SignalOutcomeTracker(settings=..., db=...)`` with the
    default CWD-relative ``results_dir="results"``. Tests that run ``scan_once``
    without injecting a tracker would otherwise write ``signal_outcome_open.json``
    / ``signal_outcomes.csv`` into the repository tree. The tracker's own unit
    tests construct the class directly with ``tmp_path`` and are unaffected.
    """
    import bist_bot.scanner as scanner_module

    monkeypatch.setattr(
        scanner_module,
        "SignalOutcomeTracker",
        lambda *args, **kwargs: MagicMock(),
    )


@pytest.fixture(autouse=True)
def _stub_default_shadow_trade_service(monkeypatch):
    """Keep ScanService's default ShadowTradeService out of the real results/ dir.

    ScanService builds ``ShadowTradeService(...)`` with the default
    CWD-relative ``results_dir="results"``. Tests that run ``scan_once``
    without injecting a service would otherwise write ``shadow_open.json`` /
    ``shadow_pnl.csv`` / ``shadow_summary_state.json`` into the repository
    tree. The service's own unit tests construct the class directly with
    ``tmp_path`` and are unaffected.
    """
    import bist_bot.scanner as scanner_module

    monkeypatch.setattr(
        scanner_module,
        "ShadowTradeService",
        lambda *args, **kwargs: MagicMock(),
    )
