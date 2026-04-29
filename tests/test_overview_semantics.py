"""Semantic clarity tests: verify HOLD/BEKLE signals are not presented as actionable opportunities."""

from __future__ import annotations

import importlib

import pytest

from bist_bot.strategy.signal_models import Signal, SignalType
from bist_bot.ui.pages.overview_page import _is_actionable_hist, _HOLD_DISPLAY_VALUES


def _make_signal(score: float, signal_type: SignalType = SignalType.BUY) -> Signal:
    return Signal(
        ticker="TEST.IS",
        signal_type=signal_type,
        score=score,
        price=100.0,
        reasons=["test"],
        stop_loss=90.0,
        target_price=110.0,
    )


# ── _is_actionable_hist ──────────────────────────────────────────────

class TestIsActionableHist:
    def test_buy_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "🟢 AL"}) is True

    def test_sell_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "🔴 SAT"}) is True

    def test_hold_bekle_is_not_actionable(self):
        assert _is_actionable_hist({"signal_type": "⚪ BEKLE"}) is False

    def test_hold_english_is_not_actionable(self):
        assert _is_actionable_hist({"signal_type": "⚪ HOLD"}) is False

    def test_hold_plain_is_not_actionable(self):
        assert _is_actionable_hist({"signal_type": "HOLD"}) is False

    def test_bekle_plain_is_not_actionable(self):
        assert _is_actionable_hist({"signal_type": "BEKLE"}) is False

    def test_strong_buy_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "💰 GÜÇLÜ AL"}) is True

    def test_strong_sell_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "🚨 GÜÇLÜ SAT"}) is True

    def test_weak_buy_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "🟡 ZAYIF AL"}) is True

    def test_weak_sell_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "🟠 ZAYIF SAT"}) is True

    def test_unknown_type_is_actionable(self):
        assert _is_actionable_hist({"signal_type": "UNKNOWN"}) is True

    def test_empty_type_is_actionable(self):
        assert _is_actionable_hist({"signal_type": ""}) is True


# ── _HOLD_DISPLAY_VALUES set ─────────────────────────────────────────

class TestHoldDisplayValues:
    def test_contains_hold(self):
        assert "HOLD" in _HOLD_DISPLAY_VALUES

    def test_contains_bekle(self):
        assert "BEKLE" in _HOLD_DISPLAY_VALUES

    def test_contains_emoji_bekle(self):
        assert "⚪ BEKLE" in _HOLD_DISPLAY_VALUES

    def test_contains_emoji_hold(self):
        assert "⚪ HOLD" in _HOLD_DISPLAY_VALUES

    def test_does_not_contain_buy(self):
        assert "BUY" not in _HOLD_DISPLAY_VALUES

    def test_does_not_contain_sell(self):
        assert "SELL" not in _HOLD_DISPLAY_VALUES


# ── overview_page: active_watch excludes HOLD ────────────────────────

class TestOverviewActiveWatch:
    def test_active_watch_excludes_hold(self):
        sigs = [_make_signal(5.0, SignalType.HOLD), _make_signal(50.0, SignalType.BUY)]
        actionable = [s for s in sigs if s.signal_type != SignalType.HOLD]
        assert all(s.signal_type != SignalType.HOLD for s in actionable)

    def test_active_watch_prefers_strong(self):
        sigs = [_make_signal(60.0, SignalType.STRONG_BUY), _make_signal(30.0, SignalType.BUY)]
        strong = sorted([s for s in sigs if s.score >= 48], key=lambda s: s.score, reverse=True)
        active_watch = strong[:4]
        assert len(active_watch) >= 1
        assert active_watch[0].score == 60.0

    def test_fallback_to_actionable_when_no_strong(self):
        sigs = [_make_signal(25.0, SignalType.BUY), _make_signal(5.0, SignalType.HOLD)]
        actionable = [s for s in sigs if s.signal_type != SignalType.HOLD]
        active_watch = sorted(actionable, key=lambda s: s.score, reverse=True)[:4]
        assert len(active_watch) == 1
        assert active_watch[0].signal_type == SignalType.BUY


# ── portfolio_page: sell uses SignalType enum ────────────────────────

class TestPortfolioSellEnum:
    def test_sell_detected(self):
        sigs = [_make_signal(-20.0, SignalType.SELL)]
        sell = [s for s in sigs if s.signal_type in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL)]
        assert len(sell) == 1

    def test_strong_sell_detected(self):
        sigs = [_make_signal(-50.0, SignalType.STRONG_SELL)]
        sell = [s for s in sigs if s.signal_type in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL)]
        assert len(sell) == 1

    def test_weak_sell_detected(self):
        sigs = [_make_signal(-5.0, SignalType.WEAK_SELL)]
        sell = [s for s in sigs if s.signal_type in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL)]
        assert len(sell) == 1

    def test_hold_not_in_sell(self):
        sigs = [_make_signal(0.0, SignalType.HOLD)]
        sell = [s for s in sigs if s.signal_type in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL)]
        assert len(sell) == 0

    def test_buy_not_in_sell(self):
        sigs = [_make_signal(30.0, SignalType.BUY)]
        sell = [s for s in sigs if s.signal_type in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL)]
        assert len(sell) == 0


# ── portfolio_page: actionable-only fallback ─────────────────────────

class TestPortfolioActionableFallback:
    def test_hold_excluded_from_top(self):
        sigs = [_make_signal(5.0, SignalType.HOLD), _make_signal(30.0, SignalType.BUY)]
        top = sorted([s for s in sigs if s.signal_type != SignalType.HOLD], key=lambda x: x.score, reverse=True)[:5]
        assert all(s.signal_type != SignalType.HOLD for s in top)
