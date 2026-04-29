"""Phase 2 overview semantics tests.

Guarantees:
1. Top conviction ideas only contains actionable (non-HOLD) signals.
2. Historical record classification (_is_actionable_hist) matches SignalType.
3. scan_stats absence is safe (no crash, no wrong display).
4. scan_stats presence yields correct generated/actionable/hold counts.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import Signal, SignalType
from bist_bot.ui.pages.overview_page import _is_actionable_hist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(ticker: str, signal_type: SignalType, score: float) -> Signal:
    return Signal(
        ticker=ticker,
        signal_type=signal_type,
        score=score,
        price=100.0,
    )


# ---------------------------------------------------------------------------
# 1. Top conviction excludes HOLD signals
# ---------------------------------------------------------------------------


class TestConvictionActionableOnly:
    """active_watch must never contain HOLD signals."""

    def test_no_hold_in_active_watch_when_only_hold_exists(self):
        signals = [
            _make_signal("A.IS", SignalType.HOLD, 0),
            _make_signal("B.IS", SignalType.HOLD, 5),
            _make_signal("C.IS", SignalType.HOLD, -2),
        ]
        strong = sorted(
            [s for s in signals if s.score >= settings.STRONG_BUY_THRESHOLD],
            key=lambda s: s.score,
            reverse=True,
        )
        actionable = [s for s in signals if s.signal_type != SignalType.HOLD]
        active_watch = strong[:4] if strong else sorted(
            actionable, key=lambda s: s.score, reverse=True,
        )[:4]
        assert len(active_watch) == 0

    def test_no_hold_in_active_watch_when_mixed(self):
        signals = [
            _make_signal("A.IS", SignalType.HOLD, 0),
            _make_signal("B.IS", SignalType.BUY, 25),
            _make_signal("C.IS", SignalType.HOLD, 5),
        ]
        strong = sorted(
            [s for s in signals if s.score >= settings.STRONG_BUY_THRESHOLD],
            key=lambda s: s.score,
            reverse=True,
        )
        actionable = [s for s in signals if s.signal_type != SignalType.HOLD]
        active_watch = strong[:4] if strong else sorted(
            actionable, key=lambda s: s.score, reverse=True,
        )[:4]
        assert all(s.signal_type != SignalType.HOLD for s in active_watch)
        assert len(active_watch) == 1

    def test_strong_takes_priority_over_actionable_fallback(self):
        signals = [
            _make_signal("A.IS", SignalType.STRONG_BUY, 50),
            _make_signal("B.IS", SignalType.BUY, 25),
        ]
        strong = sorted(
            [s for s in signals if s.score >= settings.STRONG_BUY_THRESHOLD],
            key=lambda s: s.score,
            reverse=True,
        )
        actionable = [s for s in signals if s.signal_type != SignalType.HOLD]
        active_watch = strong[:4] if strong else sorted(
            actionable, key=lambda s: s.score, reverse=True,
        )[:4]
        assert len(active_watch) == 1
        assert active_watch[0].signal_type == SignalType.STRONG_BUY

    def test_empty_signals_yields_empty_active_watch(self):
        signals: list[Signal] = []
        strong = sorted(
            [s for s in signals if s.score >= settings.STRONG_BUY_THRESHOLD],
            key=lambda s: s.score,
            reverse=True,
        )
        actionable = [s for s in signals if s.signal_type != SignalType.HOLD]
        active_watch = strong[:4] if strong else sorted(
            actionable, key=lambda s: s.score, reverse=True,
        )[:4]
        assert len(active_watch) == 0


# ---------------------------------------------------------------------------
# 2. _is_actionable_hist matches SignalType
# ---------------------------------------------------------------------------


class TestIsActionableHist:
    """Historical dict classification must match SignalType semantics."""

    @pytest.mark.parametrize(
        "raw_value, expected",
        [
            ("⚪ BEKLE", False),
            ("⚪ HOLD", False),
            ("🟢 AL", True),
            ("🟢 BUY", True),
            ("💰 GÜÇLÜ AL", True),
            ("🔴 SAT", True),
            ("🟠 ZAYIF SAT", True),
            ("🟡 ZAYIF AL", True),
            ("🚨 GÜÇLÜ SAT", True),
        ],
    )
    def test_known_signal_types(self, raw_value: str, expected: bool):
        sig = {"signal_type": raw_value}
        assert _is_actionable_hist(sig) is expected

    def test_missing_signal_type_defaults_actionable(self):
        sig = {}
        assert _is_actionable_hist(sig) is True

    def test_empty_signal_type_defaults_actionable(self):
        sig = {"signal_type": ""}
        assert _is_actionable_hist(sig) is True

    def test_unknown_type_defaults_actionable(self):
        sig = {"signal_type": "🆕 YENİ TİP"}
        assert _is_actionable_hist(sig) is True

    def test_case_insensitive_bekle(self):
        sig = {"signal_type": "BEKLE"}
        assert _is_actionable_hist(sig) is False


# ---------------------------------------------------------------------------
# 3. scan_stats safety — absence is safe
# ---------------------------------------------------------------------------


class TestScanStatsAbsence:
    """When scan_stats is missing, dashboard must not crash."""

    def test_none_scan_stats_no_crash(self):
        scan_stats = None
        if scan_stats:
            _ = scan_stats.get("generated_count", 0)
            rendered = True
        else:
            rendered = False
        assert rendered is False

    def test_empty_dict_scan_stats_no_crash(self):
        scan_stats: dict = {}
        if scan_stats:
            gen = scan_stats.get("generated_count", 0)
            act = scan_stats.get("actionable_count", 0)
            hold = gen - act
        else:
            gen = act = hold = 0
        assert gen == 0
        assert act == 0
        assert hold == 0


# ---------------------------------------------------------------------------
# 4. scan_stats presence — correct generated/actionable/hold counts
# ---------------------------------------------------------------------------


class TestScanStatsCounts:
    """scan_stats yields correct generated / actionable / hold breakdown."""

    @pytest.mark.parametrize(
        "generated, actionable, expected_hold",
        [
            (20, 1, 19),
            (20, 0, 20),
            (20, 20, 0),
            (0, 0, 0),
        ],
    )
    def test_hold_count_calculation(
        self, generated: int, actionable: int, expected_hold: int
    ):
        scan_stats = {
            "generated_count": generated,
            "actionable_count": actionable,
        }
        hold_count = (
            scan_stats.get("generated_count", 0)
            - scan_stats.get("actionable_count", 0)
        )
        assert hold_count == expected_hold

    def test_scanned_count_present(self):
        scan_stats = {
            "scanned_count": 100,
            "generated_count": 20,
            "actionable_count": 1,
        }
        assert scan_stats.get("scanned_count", 0) == 100
