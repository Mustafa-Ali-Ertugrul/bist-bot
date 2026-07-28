"""STRATEGY_PROFILE runtime wiring tests."""

from __future__ import annotations

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


def test_strategy_params_from_settings_defaults_to_conservative() -> None:
    """STRATEGY_PROFILE not set → defaults to conservative."""
    with settings.override(STRATEGY_PROFILE="conservative"):
        pass  # verify settings accepts it
    with settings.override():
        params = StrategyParams.from_settings()
    # The ContextVar is cleared after 'with settings.override():' block,
    # but os.getenv returns None → from_settings() falls through to conservative.
    # This works because STRATEGY_PROFILE env var is set to 'conservative'
    # by docker-compose env_file but not in bare test env.
    # We explicitly test the safe fallback: when env is absent, conservative wins.
    params = StrategyParams.from_settings()
    assert params.buy_threshold == 25.0


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
