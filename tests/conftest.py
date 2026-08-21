import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


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
