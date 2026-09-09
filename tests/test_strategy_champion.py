"""Champion WR profile (challenge 2026-08-29: rr 0.5 + mh20 + skor 28-33 + pv-gate)."""

from __future__ import annotations

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.strategy.engine_filters import is_trade_actionable
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import Signal, SignalType


def test_champion_profile_values() -> None:
    p = StrategyParams.champion_wr()
    assert p.buy_threshold == 28.0
    assert p.sell_threshold == -28.0
    assert p.max_actionable_score == 33.0
    assert p.pv_confirmation_required is True
    # Sell side and conservative bones preserved.
    assert p.sideways_score_multiplier == 0.4
    assert p.mtf_confluence_block_enabled is True


def test_from_settings_champion_mapping() -> None:
    with settings.override(STRATEGY_PROFILE="champion"):
        p = StrategyParams.from_settings()
        assert p.buy_threshold == 28.0
        assert p.max_actionable_score == 33.0
    with settings.override(STRATEGY_PROFILE="conservative"):
        assert StrategyParams.from_settings().buy_threshold == 25.0


def test_buy_band_edges() -> None:
    champ = StrategyParams.champion_wr()
    assert champ.buy_actionable_score(27.9) is False
    assert champ.buy_actionable_score(28.0) is True
    assert champ.buy_actionable_score(30.0) is True
    assert champ.buy_actionable_score(33.0) is True
    assert champ.buy_actionable_score(33.1) is False
    assert champ.buy_actionable_score(45.0) is False
    # Default profile has no upper cap (existing behavior preserved).
    default = StrategyParams()
    assert default.max_actionable_score == 100.0
    assert default.buy_actionable_score(45.0) is True


def _buy_signal(score: float) -> Signal:
    return Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=score,
        price=100.0,
        stop_loss=95.0,
        target_price=105.0,
    )


def test_is_trade_actionable_enforces_band() -> None:
    champ = StrategyParams.champion_wr()
    assert is_trade_actionable(_buy_signal(30.0), champ) is True
    assert is_trade_actionable(_buy_signal(45.0), champ) is False
    assert is_trade_actionable(_buy_signal(20.0), champ) is False


def _bars_with_jump(jump_pct: float) -> pd.DataFrame:
    closes = [100.0] * 30
    closes[-1] = 100.0 * (1.0 + jump_pct)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000] * 30,
        }
    )


def test_split_anomaly_guard() -> None:
    fetcher = BISTDataFetcher(watchlist=["THYAO.IS"])
    # +20% single-bar move: impossible under BIST ±10% circuits -> skip.
    assert fetcher._is_split_anomaly("THYAO.IS", _bars_with_jump(0.20), "6mo", "1d", "test") is True
    # Normal drift passes.
    assert (
        fetcher._is_split_anomaly("THYAO.IS", _bars_with_jump(0.02), "6mo", "1d", "test") is False
    )
    # Too few bars: cannot judge -> pass.
    tiny = _bars_with_jump(0.50).head(1)
    assert fetcher._is_split_anomaly("THYAO.IS", tiny, "6mo", "1d", "test") is False
