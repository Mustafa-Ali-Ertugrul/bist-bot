"""Tests for BIST price ticks and rounding correctness."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pytest  # noqa: E402

from bist_bot.risk.ticks import get_tick_size, round_to_tick  # noqa: E402


@pytest.mark.parametrize(
    ("price", "expected_tick"),
    [
        (5.00, 0.01),  # < 20 -> 0.01
        (19.99, 0.01),
        (20.00, 0.02),  # 20 <= p < 50 -> 0.02
        (49.99, 0.02),
        (50.00, 0.05),  # 50 <= p < 100 -> 0.05 (user's target 50 TL threshold check)
        (99.99, 0.05),
        (100.00, 0.10),  # 100 <= p < 250 -> 0.10 (user's target 100 TL threshold check)
        (249.90, 0.10),
        (250.00, 0.20),  # 250 <= p < 500 -> 0.20
        (499.00, 0.20),
        (500.00, 0.50),  # 500 <= p < 1000 -> 0.50
        (999.00, 0.50),
        (1000.00, 1.00),  # >= 1000 -> 1.00
        (5000.00, 1.00),
    ],
)
def test_bist_tick_sizes_correct(price: float, expected_tick: float):
    assert get_tick_size(price) == expected_tick


@pytest.mark.parametrize(
    ("price", "side", "expected_rounded"),
    [
        # p < 20 (tick=0.01)
        (15.234, "BUY", 15.24),
        (15.234, "SELL", 15.23),
        # 20 <= p < 50 (tick=0.02)
        (30.01, "BUY", 30.02),
        (30.01, "SELL", 30.00),
        # 50 <= p < 100 (tick=0.05)
        (75.02, "BUY", 75.05),
        (75.02, "SELL", 75.00),
        # 100 <= p < 250 (tick=0.10)
        (150.15, "BUY", 150.20),
        (150.15, "SELL", 150.10),
        # 250 <= p < 500 (tick=0.20)
        (300.11, "BUY", 300.20),
        (300.11, "SELL", 300.00),
        # 500 <= p < 1000 (tick=0.50)
        (600.35, "BUY", 600.50),
        (600.35, "SELL", 600.00),
        # p >= 1000 (tick=1.00)
        (1500.20, "BUY", 1501.00),
        (1500.20, "SELL", 1500.00),
    ],
)
def test_round_to_tick_rounding(price: float, side: str, expected_rounded: float):
    assert round_to_tick(price, side) == expected_rounded


def test_round_to_tick_handles_zero_and_negative():
    assert round_to_tick(0.0) == 0.0
    assert round_to_tick(-5.50) == 0.0
