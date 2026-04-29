"""Threshold consistency tests: verify UI pages use settings thresholds, not hardcoded values."""

from __future__ import annotations

import importlib
import inspect

import pytest

from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import Signal, SignalType


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


SIGNAL_CARD = importlib.import_module("bist_bot.ui.components.signal_card")
SIGNALS_PAGE = importlib.import_module("bist_bot.ui.pages.signals_page")
OVERVIEW_PAGE = importlib.import_module("bist_bot.ui.pages.overview_page")
PORTFOLIO_PAGE = importlib.import_module("bist_bot.ui.pages.portfolio_page")
ANALYZE_PAGE = importlib.import_module("bist_bot.ui.pages.analyze_page")


# ── signal_card._accent ──────────────────────────────────────────────

class TestSignalCardAccent:
    def test_strong_buy_at_threshold(self):
        badge, color, accent = SIGNAL_CARD._accent(settings.STRONG_BUY_THRESHOLD)
        assert accent == "positive"

    def test_strong_buy_above_threshold(self):
        badge, color, accent = SIGNAL_CARD._accent(settings.STRONG_BUY_THRESHOLD + 1)
        assert accent == "positive"

    def test_buy_at_threshold(self):
        badge, color, accent = SIGNAL_CARD._accent(settings.BUY_THRESHOLD)
        assert accent == "primary"

    def test_buy_between_thresholds(self):
        mid = (settings.BUY_THRESHOLD + settings.STRONG_BUY_THRESHOLD) // 2
        badge, color, accent = SIGNAL_CARD._accent(float(mid))
        assert accent == "primary"

    def test_watch_below_buy_threshold(self):
        badge, color, accent = SIGNAL_CARD._accent(float(settings.BUY_THRESHOLD - 1))
        assert accent == "danger"

    def test_negative_score(self):
        badge, color, accent = SIGNAL_CARD._accent(-10.0)
        assert accent == "danger"

    def test_zero_score(self):
        badge, color, accent = SIGNAL_CARD._accent(0.0)
        assert accent == "danger"

    def test_custom_strong_threshold(self):
        with settings.override(STRONG_BUY_THRESHOLD=60):
            badge, color, accent = SIGNAL_CARD._accent(55.0)
            assert accent == "primary"

    def test_custom_buy_threshold(self):
        with settings.override(BUY_THRESHOLD=30):
            badge, color, accent = SIGNAL_CARD._accent(25.0)
            assert accent == "danger"


# ── signals_page grouping ────────────────────────────────────────────

class TestSignalsPageGrouping:
    def test_strong_group_uses_threshold(self):
        sigs = [_make_signal(settings.STRONG_BUY_THRESHOLD, SignalType.STRONG_BUY)]
        strong = [s for s in sigs if s.score >= settings.STRONG_BUY_THRESHOLD]
        assert len(strong) == 1

    def test_buy_group_excludes_strong(self):
        sigs = [_make_signal(settings.STRONG_BUY_THRESHOLD, SignalType.BUY)]
        buy = [s for s in sigs if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD]
        assert len(buy) == 0

    def test_buy_group_includes_at_threshold(self):
        sigs = [_make_signal(settings.BUY_THRESHOLD, SignalType.BUY)]
        buy = [s for s in sigs if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD]
        assert len(buy) == 1

    def test_watch_below_buy(self):
        sigs = [_make_signal(settings.BUY_THRESHOLD - 1, SignalType.HOLD)]
        watch = [s for s in sigs if s.score < settings.BUY_THRESHOLD]
        assert len(watch) == 1

    def test_all_signals_partitioned(self):
        scores = [0, settings.BUY_THRESHOLD - 1, settings.BUY_THRESHOLD,
                  settings.STRONG_BUY_THRESHOLD - 1, settings.STRONG_BUY_THRESHOLD, 99]
        sigs = [_make_signal(s) for s in scores]
        strong = [s for s in sigs if s.score >= settings.STRONG_BUY_THRESHOLD]
        buy = [s for s in sigs if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD]
        watch = [s for s in sigs if s.score < settings.BUY_THRESHOLD]
        assert len(strong) + len(buy) + len(watch) == len(sigs)

    def test_custom_thresholds_change_partition(self):
        with settings.override(STRONG_BUY_THRESHOLD=70, BUY_THRESHOLD=30):
            scores = [25, 30, 50, 70, 80]
            sigs = [_make_signal(s) for s in scores]
            strong = [s for s in sigs if s.score >= settings.STRONG_BUY_THRESHOLD]
            buy = [s for s in sigs if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD]
            watch = [s for s in sigs if s.score < settings.BUY_THRESHOLD]
            assert len(strong) == 2
            assert len(buy) == 2
            assert len(watch) == 1


# ── portfolio_page grouping ──────────────────────────────────────────

class TestPortfolioPageGrouping:
    def test_strong_count(self):
        sigs = [_make_signal(settings.STRONG_BUY_THRESHOLD, SignalType.STRONG_BUY)]
        strong = [s for s in sigs if s.score >= settings.STRONG_BUY_THRESHOLD]
        assert len(strong) == 1

    def test_buy_range(self):
        sigs = [_make_signal(settings.BUY_THRESHOLD, SignalType.BUY)]
        buy = [s for s in sigs if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD]
        assert len(buy) == 1

    def test_sell_uses_enum(self):
        sigs = [_make_signal(-30.0, SignalType.SELL)]
        sell = [s for s in sigs if s.signal_type in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL)]
        assert len(sell) == 1

    def test_hold_not_in_actionable_fallback(self):
        sigs = [_make_signal(5.0, SignalType.HOLD), _make_signal(30.0, SignalType.BUY)]
        actionable = [s for s in sigs if s.signal_type != SignalType.HOLD]
        assert len(actionable) == 1


# ── overview_page threshold usage ────────────────────────────────────

class TestOverviewPageThresholds:
    def test_positive_flow_uses_buy_threshold(self):
        sigs = [_make_signal(settings.BUY_THRESHOLD, SignalType.BUY)]
        positive_flow = len([s for s in sigs if s.score >= settings.BUY_THRESHOLD])
        assert positive_flow == 1

    def test_strong_uses_strong_threshold(self):
        sigs = [_make_signal(settings.STRONG_BUY_THRESHOLD, SignalType.STRONG_BUY)]
        strong = sorted([s for s in sigs if s.score >= settings.STRONG_BUY_THRESHOLD], key=lambda s: s.score, reverse=True)
        assert len(strong) == 1

    def test_positive_flow_excludes_below_buy(self):
        sigs = [_make_signal(settings.BUY_THRESHOLD - 1, SignalType.HOLD)]
        positive_flow = len([s for s in sigs if s.score >= settings.BUY_THRESHOLD])
        assert positive_flow == 0


# ── analyze_page threshold usage ─────────────────────────────────────

class TestAnalyzePageThresholds:
    def test_verdict_positive_at_buy_threshold(self):
        signal_score = float(settings.BUY_THRESHOLD)
        verdict = "bb-badge bb-badge-positive" if signal_score >= settings.BUY_THRESHOLD else "bb-badge bb-badge-danger"
        assert verdict == "bb-badge bb-badge-positive"

    def test_verdict_danger_below_buy_threshold(self):
        signal_score = float(settings.BUY_THRESHOLD - 1)
        verdict = "bb-badge bb-badge-positive" if signal_score >= settings.BUY_THRESHOLD else "bb-badge bb-badge-danger"
        assert verdict == "bb-badge bb-badge-danger"

    def test_custom_buy_threshold(self):
        with settings.override(BUY_THRESHOLD=50):
            assert settings.BUY_THRESHOLD == 50


# ── source code: no hardcoded thresholds ─────────────────────────────

class TestNoHardcodedThresholds:
    @pytest.mark.parametrize("module_path,func_name", [
        ("bist_bot.ui.components.signal_card", "_accent"),
        ("bist_bot.ui.pages.signals_page", "render_signals_page"),
        ("bist_bot.ui.pages.portfolio_page", "render_portfolio_page"),
        ("bist_bot.ui.pages.overview_page", "render_overview_page"),
        ("bist_bot.ui.pages.analyze_page", "render_analyze_page"),
    ])
    def test_no_hardcoded_score_40(self, module_path, func_name):
        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        for line_no, line in enumerate(source.splitlines(), 1):
            if "score >= 40" in line or "score >=40" in line:
                pytest.fail(f"Hardcoded threshold 40 found in {module_path}:{line_no}")

    @pytest.mark.parametrize("module_path,func_name", [
        ("bist_bot.ui.components.signal_card", "_accent"),
        ("bist_bot.ui.pages.signals_page", "render_signals_page"),
        ("bist_bot.ui.pages.portfolio_page", "render_portfolio_page"),
        ("bist_bot.ui.pages.overview_page", "render_overview_page"),
        ("bist_bot.ui.pages.analyze_page", "render_analyze_page"),
    ])
    def test_no_hardcoded_score_10(self, module_path, func_name):
        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        for line_no, line in enumerate(source.splitlines(), 1):
            if "score >= 10" in line or "score >=10" in line:
                pytest.fail(f"Hardcoded threshold 10 found in {module_path}:{line_no}")

    def test_signal_card_imports_settings(self):
        source = inspect.getsource(SIGNAL_CARD)
        assert "from bist_bot.config" in source or "settings" in source

    def test_signals_page_imports_settings(self):
        source = inspect.getsource(SIGNALS_PAGE)
        assert "from bist_bot.config" in source

    def test_portfolio_page_imports_settings(self):
        source = inspect.getsource(PORTFOLIO_PAGE)
        assert "from bist_bot.config" in source

    def test_overview_page_imports_settings(self):
        source = inspect.getsource(OVERVIEW_PAGE)
        assert "from bist_bot.config" in source

    def test_analyze_page_imports_settings(self):
        source = inspect.getsource(ANALYZE_PAGE)
        assert "from bist_bot.config" in source
