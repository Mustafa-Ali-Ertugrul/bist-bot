"""Risk manager portfolio controls tests."""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from risk_manager import RiskLevels, RiskManager


def build_frame(scale: float = 1.0, atr: float = 2.0) -> pd.DataFrame:
    rows = []
    for idx in range(40):
        base = 100 + idx * scale
        rows.append(
            {
                "open": base,
                "high": base + 2,
                "low": base - 2,
                "close": base + 1,
                "atr": atr,
            }
        )
    return pd.DataFrame(rows)


def test_high_atr_reduces_position_size():
    manager = RiskManager(capital=10000)
    low_vol = manager.calculate(build_frame(1.0, atr=1.0))
    high_vol = manager.calculate(build_frame(1.0, atr=8.0))

    assert high_vol.volatility_scale < low_vol.volatility_scale
    assert high_vol.position_size < low_vol.position_size


def test_correlation_risk_limit_scales_position_and_matrix():
    manager = RiskManager(capital=10000)
    existing = build_frame(1.0, atr=2.0)
    candidate = build_frame(1.02, atr=2.0)

    manager.register_position("XBANK.IS", existing)
    base_levels = manager.calculate(candidate)
    adjusted = manager.apply_portfolio_risk("AKBNK.IS", candidate, base_levels)

    matrix = manager.get_correlation_matrix()

    assert adjusted.correlated_tickers == ["XBANK.IS"]
    assert adjusted.correlation_scale < 1.0
    assert adjusted.position_size > 0
    assert "XBANK.IS" in matrix.index


def test_correlation_cluster_can_block_new_position():
    manager = RiskManager(capital=10000)
    manager.register_position("AKBNK.IS", build_frame(1.0, atr=2.0))
    manager.register_position("GARAN.IS", build_frame(1.01, atr=2.0))
    manager.register_position("YKBNK.IS", build_frame(1.02, atr=2.0))

    levels = manager.apply_portfolio_risk(
        "ISCTR.IS",
        build_frame(1.03, atr=2.0),
        RiskLevels(final_stop=95.0, final_target=110.0, volatility_scale=1.0),
    )

    assert levels.blocked_by_correlation is True
    assert levels.position_size == 0


def test_position_size_is_never_negative():
    manager = RiskManager(capital=10000)
    levels = manager.calculate(build_frame(1.0, atr=2.0))

    assert levels.position_size >= 0


def test_stop_loss_is_below_entry_price():
    manager = RiskManager(capital=10000)
    df = build_frame(1.0, atr=2.0)
    entry_price = float(df["close"].iloc[-1])
    levels = manager.calculate(df)

    assert levels.final_stop < entry_price


def test_zero_capital_raises_error():
    with pytest.raises(ValueError):
        RiskManager(capital=0)
