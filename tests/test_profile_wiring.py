"""STRATEGY_PROFILE runtime wiring tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from bist_bot.config.settings import settings
from bist_bot.strategy.engine import StrategyEngine
from bist_bot.strategy.params import StrategyParams


def test_strategy_params_from_settings_returns_conservative() -> None:
    """STRATEGY_PROFILE=conservative gives conservative params."""
    with settings.override(STRATEGY_PROFILE="conservative"):
        params = StrategyParams.from_settings()
    assert params.buy_threshold == 25.0
    assert params.counter_trend_multiplier == 0.0


def test_strategy_params_from_settings_returns_default_for_non_conservative() -> None:
    """STRATEGY_PROFILE=default (or anything else) gives default params."""
    with settings.override(STRATEGY_PROFILE="default"):
        params = StrategyParams.from_settings()
    assert params.buy_threshold == 20.0
    assert params.counter_trend_multiplier == 0.3


def test_strategy_params_from_settings_defaults_to_conservative(tmp_path: Path) -> None:
    """STRATEGY_PROFILE nowhere (clean env + no .env file) → conservative.

    Runs in a subprocess because the setting is baked at import time via
    dotenv; this keeps the test hermetic regardless of the developer's
    local .env (e.g. STRATEGY_PROFILE=champion).
    """
    repo_root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "STRATEGY_PROFILE"}
    env["PYTHONPATH"] = str(repo_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from bist_bot.strategy.params import StrategyParams; "
            "print(StrategyParams.from_settings().buy_threshold)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "25.0"


def test_engine_uses_conservative_params_by_default() -> None:
    """StrategyEngine with no explicit params uses STRATEGY_PROFILE=conservative."""
    with settings.override(STRATEGY_PROFILE="conservative"):
        engine = StrategyEngine()
    assert engine.params.buy_threshold == 25.0
    assert engine.params.counter_trend_multiplier == 0.0


def test_engine_uses_default_params_when_profile_is_default() -> None:
    """StrategyEngine with STRATEGY_PROFILE=default uses regular params."""
    with settings.override(STRATEGY_PROFILE="default"):
        engine = StrategyEngine()
    assert engine.params.buy_threshold == 20.0
    assert engine.params.counter_trend_multiplier == 0.3
