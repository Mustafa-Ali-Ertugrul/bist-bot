"""Persistence tests for risk manager position continuity."""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.db import DataAccess, DatabaseManager  # noqa: E402
from bist_bot.risk import RiskLevels, RiskManager  # noqa: E402


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


def test_risk_manager_restores_open_paper_position_state_after_restart(tmp_path):
    db = DataAccess(DatabaseManager(sqlite_path=str(tmp_path / "risk_restart.db")))
    db.add_paper_trade(
        ticker="XBANK.IS",
        signal_type="BUY",
        signal_price=100.0,
        signal_time=datetime(2025, 1, 1, 10, 0, 0),
        stop_loss=95.0,
        target_price=110.0,
        score=20,
        regime="TRENDING",
    )

    restarted = RiskManager(capital=10000, position_repository=db)
    data = {
        "XBANK.IS": {"trend": build_frame(1.0, atr=2.0)},
        "AKBNK.IS": {"trend": build_frame(1.02, atr=2.0)},
    }

    restarted.reset_portfolio()
    restarted.build_global_correlation_cache(data)

    assert "XBANK.IS" in restarted._portfolio_history


def test_correlation_check_uses_restored_open_positions_after_restart(tmp_path):
    db = DataAccess(DatabaseManager(sqlite_path=str(tmp_path / "risk_corr_restart.db")))
    db.create_order(
        ticker="XBANK.IS",
        side="BUY",
        quantity=10,
        order_type="MARKET",
        price=100.0,
        state="FILLED",
        filled_qty=10,
        avg_fill_price=100.0,
    )

    restarted = RiskManager(capital=10000, position_repository=db)
    existing = build_frame(1.0, atr=2.0)
    candidate = build_frame(1.02, atr=2.0)
    restarted.build_global_correlation_cache(
        {
            "XBANK.IS": {"trend": existing},
            "AKBNK.IS": {"trend": candidate},
        }
    )

    adjusted = restarted.apply_portfolio_risk(
        "AKBNK.IS",
        candidate,
        RiskLevels(final_stop=95.0, final_target=110.0, volatility_scale=1.0),
    )

    assert adjusted.correlated_tickers == ["XBANK.IS"]
    assert adjusted.correlation_scale < 1.0
