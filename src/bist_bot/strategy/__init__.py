"""Strategy package exports.

Heavy dependencies (engine, regime, params) are loaded lazily so that lighter
modules such as :mod:`bist_bot.strategy.signal_models` can be imported even
when optional ML dependencies (e.g. scikit-learn) are not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bist_bot.strategy.signal_models import Signal, SignalType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bist_bot.strategy.engine import StrategyEngine
    from bist_bot.strategy.params import StrategyParams
    from bist_bot.strategy.regime import MarketRegime, TrendBias

__all__ = ["MarketRegime", "Signal", "SignalType", "StrategyEngine", "StrategyParams", "TrendBias"]


_LAZY_ATTRS: dict[str, str] = {
    "StrategyEngine": "bist_bot.strategy.engine",
    "StrategyParams": "bist_bot.strategy.params",
    "MarketRegime": "bist_bot.strategy.regime",
    "TrendBias": "bist_bot.strategy.regime",
}


def __getattr__(name: str) -> Any:
    """Lazily import heavy strategy submodules on first attribute access."""
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'bist_bot.strategy' has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
