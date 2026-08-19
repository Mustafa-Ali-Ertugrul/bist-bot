"""Explainable scoring — score_breakdown pipeline tests."""

from __future__ import annotations

from bist_bot.strategy.signal_models import Signal, SignalType


def test_signal_has_score_breakdown() -> None:
    sig = Signal(
        ticker="XU100.IS",
        signal_type=SignalType.BUY,
        score=50.0,
        price=1.0,
        score_breakdown={"a": 10.0, "b": -5.0, "c": 2.0},
    )
    assert sig.score_breakdown == {"a": 10.0, "b": -5.0, "c": 2.0}
    top = sig.top_contributors(count=2)
    assert len(top) == 2
    assert top[0][0] == "a"  # highest abs
    assert top[1][0] == "b"


def test_signal_top_contributors_sorted_by_abs() -> None:
    sig = Signal(
        ticker="A.IS",
        signal_type=SignalType.STRONG_BUY,
        score=10.0,
        price=10.0,
        score_breakdown={"neg": -8.0, "pos1": 3.0, "pos2": 5.0},
    )
    top = sig.top_contributors(count=3)
    names = [n for n, _ in top]
    assert names[0] == "neg"  # abs 8
    assert names[1] == "pos2"  # abs 5
    assert names[2] == "pos1"  # abs 3


def test_signal_top_contributors_empty_when_no_breakdown() -> None:
    sig = Signal(ticker="B.IS", signal_type=SignalType.HOLD, score=0.0, price=1.0)
    assert sig.top_contributors() == []


def test_with_locale_preserves_score_breakdown() -> None:
    original = Signal(
        ticker="C.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        price=50.0,
        score_breakdown={"m": 10.0, "t": 5.0},
    )
    loc = original.with_locale("tr")
    assert loc.score_breakdown == {"m": 10.0, "t": 5.0}
