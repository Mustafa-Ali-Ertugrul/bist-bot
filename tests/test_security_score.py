from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_security_score_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "security_score.py"
    spec = importlib.util.spec_from_file_location("security_score", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase1_security_score_weights_warn_findings_at_half() -> None:
    result = _load_security_score_module().calculate()

    assert result["baseline_score"] == 73.5
    assert result["open_score"] == 51.0
    assert result["open_count"] == 20
    assert result["status_counts"] == {"fixed": 3, "mitigated_warn": 2, "open": 18}
