"""Unit tests for Faz 3 new modules.

Covers:
- BaseStrategy ABC enforcement
- StrategyEngine.register_strategy / unregister_strategy / scan_with_plugins
- MarketCandle Pydantic validation (schemas.py)
- RiskProfileLoader (profile.py)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from bist_bot.data.schemas import MarketCandle, validate_dataframe
from bist_bot.risk.profile import RiskProfile, RiskProfileLoader
from bist_bot.strategy.base import BaseStrategy
from bist_bot.strategy.signal_models import Signal, SignalType

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_df(rows: int = 50) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [102.0] * rows,
            "low": [98.0] * rows,
            "close": [101.0] * rows,
            "volume": [500_000] * rows,
        },
        index=dates,
    )


def _make_signal(ticker: str = "TEST.IS", score: float = 60.0) -> Signal:
    return Signal(
        ticker=ticker,
        signal_type=SignalType.BUY,
        score=score,
        price=100.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# BaseStrategy ABC
# ─────────────────────────────────────────────────────────────────────────────


class _ConcreteStrategy(BaseStrategy):
    """Minimal strategy that always returns a fixed signal."""

    @property
    def name(self) -> str:
        return "ConcreteTestStrategy"

    def analyze(self, ticker: str, data: pd.DataFrame | dict) -> Signal | None:
        return _make_signal(ticker)


class _NoSignalStrategy(BaseStrategy):
    """Strategy that never returns a signal."""

    @property
    def name(self) -> str:
        return "NoSignalStrategy"

    def analyze(self, ticker: str, data: pd.DataFrame | dict) -> Signal | None:
        return None


def test_base_strategy_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BaseStrategy()  # type: ignore[abstract]


def test_concrete_strategy_name():
    s = _ConcreteStrategy()
    assert s.name == "ConcreteTestStrategy"


def test_concrete_strategy_analyze_returns_signal():
    s = _ConcreteStrategy()
    df = _make_df()
    signal = s.analyze("ASELS.IS", df)
    assert signal is not None
    assert signal.ticker == "ASELS.IS"


def test_no_signal_strategy_returns_none():
    s = _NoSignalStrategy()
    result = s.analyze("THYAO.IS", _make_df())
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# StrategyEngine plugin registry
# ─────────────────────────────────────────────────────────────────────────────


def test_register_strategy_adds_to_registry():
    from bist_bot.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    assert len(engine._strategies) == 0
    engine.register_strategy(_ConcreteStrategy())
    assert len(engine._strategies) == 1


def test_register_multiple_strategies():
    from bist_bot.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    engine.register_strategy(_ConcreteStrategy())
    engine.register_strategy(_NoSignalStrategy())
    assert len(engine._strategies) == 2


def test_unregister_strategy_removes_by_name():
    from bist_bot.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    engine.register_strategy(_ConcreteStrategy())
    result = engine.unregister_strategy("ConcreteTestStrategy")
    assert result is True
    assert len(engine._strategies) == 0


def test_unregister_nonexistent_strategy_returns_false():
    from bist_bot.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    result = engine.unregister_strategy("DoesNotExist")
    assert result is False


def test_scan_with_plugins_no_plugins_falls_back_to_empty(monkeypatch):
    """scan_with_plugins with no plugins should behave like scan_all."""
    from bist_bot.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    # Monkeypatch scan_all to return a stable result
    monkeypatch.setattr(engine, "scan_all", lambda data: [_make_signal("MOCK.IS", 70)])
    result = engine.scan_with_plugins({"MOCK.IS": _make_df()})
    assert any(s.ticker == "MOCK.IS" for s in result)


def test_scan_with_plugins_merges_and_deduplicates(monkeypatch):
    from bist_bot.strategy.engine import StrategyEngine

    engine = StrategyEngine()
    monkeypatch.setattr(engine, "scan_all", lambda data: [_make_signal("ASELS.IS", 55)])
    engine.register_strategy(_ConcreteStrategy())  # also returns BUY for ASELS.IS with score 60

    result = engine.scan_with_plugins({"ASELS.IS": _make_df()})
    # After dedup only one BUY for ASELS.IS should remain (the higher score)
    asels_signals = [
        s for s in result if s.ticker == "ASELS.IS" and s.signal_type == SignalType.BUY
    ]
    assert len(asels_signals) == 1
    assert asels_signals[0].score == 60.0


# ─────────────────────────────────────────────────────────────────────────────
# MarketCandle Pydantic validation
# ─────────────────────────────────────────────────────────────────────────────


def test_market_candle_valid():
    candle = MarketCandle(
        timestamp=datetime(2024, 1, 1),
        open=100.0,
        high=105.0,
        low=98.0,
        close=103.0,
        volume=1_000_000,
    )
    assert candle.close == 103.0


def test_market_candle_negative_price_rejected():
    with pytest.raises(ValidationError):
        MarketCandle(
            timestamp=datetime(2024, 1, 1),
            open=-1.0,
            high=5.0,
            low=2.0,
            close=3.0,
        )


def test_validate_dataframe_valid_input():
    df = _make_df(20)
    result = validate_dataframe(df, validate=True)
    assert result is not None
    assert not result.empty
    assert "close" in result.columns


def test_validate_dataframe_none_returns_none():
    result = validate_dataframe(None)
    assert result is None


def test_validate_dataframe_fast_path():
    """validate=False should skip Pydantic, still return clean df."""
    df = _make_df(10)
    result = validate_dataframe(df, validate=False)
    assert result is not None
    assert len(result) == 10


def test_validate_dataframe_strips_nan_rows():
    df = _make_df(5)
    df.loc[df.index[2], "close"] = float("nan")
    result = validate_dataframe(df, validate=False)
    assert result is not None
    assert len(result) == 4  # NaN row dropped


# ─────────────────────────────────────────────────────────────────────────────
# RiskProfileLoader
# ─────────────────────────────────────────────────────────────────────────────


def test_risk_profile_defaults():
    profile = RiskProfile()
    assert profile.max_risk_pct == 2.0
    assert profile.max_position_cap_pct == 5.0
    assert profile.max_daily_loss_pct == 3.0


def test_risk_profile_loader_default_file():
    """Loader should succeed using the bundled default_risk_profile.yaml."""
    loader = RiskProfileLoader()
    profile = loader.load()
    assert isinstance(profile, RiskProfile)
    assert profile.max_risk_pct > 0


def test_risk_profile_loader_custom_yaml(tmp_path: Path):
    yaml_file = tmp_path / "custom_profile.yaml"
    yaml_file.write_text("max_risk_pct: 1.5\nmax_daily_loss_pct: 2.5\n")
    loader = RiskProfileLoader()
    profile = loader.load(path=yaml_file)
    assert profile.max_risk_pct == 1.5
    assert profile.max_daily_loss_pct == 2.5


def test_risk_profile_loader_custom_json(tmp_path: Path):
    import json

    json_file = tmp_path / "profile.json"
    json_file.write_text(json.dumps({"max_risk_pct": 1.0, "slippage_pct": 0.05}))
    loader = RiskProfileLoader()
    profile = loader.load(path=json_file)
    assert profile.max_risk_pct == 1.0
    assert profile.slippage_pct == 0.05


def test_risk_profile_loader_missing_file_uses_defaults():
    loader = RiskProfileLoader()
    profile = loader.load(path="/nonexistent/path/to/profile.yaml")
    # Should not raise – should return defaults
    assert isinstance(profile, RiskProfile)
    assert profile.max_risk_pct == 2.0


def test_risk_profile_loader_invalid_format(tmp_path: Path):
    bad_file = tmp_path / "profile.csv"
    bad_file.write_text("col1,col2\n1,2\n")
    loader = RiskProfileLoader()
    with pytest.raises(ValueError, match="Unsupported"):
        loader.load(path=bad_file)


def test_risk_profile_constraint_violation():
    """Values outside allowed range should raise ValidationError."""
    with pytest.raises(ValidationError):
        RiskProfile(max_risk_pct=200.0)  # exceeds le=100
