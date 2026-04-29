"""UI threshold consistency tests for signals_page grouping and signal_card accent.

Guarantees:
  1. _accent() (the real function) reads thresholds from settings.
  2. Grouping mirror logic matches _accent() band semantics.
  3. Boundary values (threshold, threshold±1) are correct.
  4. Dynamic threshold overrides propagate to both.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.config.settings import settings
from bist_bot.ui.components.signal_card import _accent

# ---------------------------------------------------------------------------
# Grouping mirror – signals_page embeds this inside a Streamlit render
# function so it cannot be imported directly.  This mirror must stay
# semantically identical to the list-comprehensions in render_signals_page().
# ---------------------------------------------------------------------------


def classify_group(score: float) -> str:
    """Mirror of signals_page grouping logic (lines 30-47)."""
    if score >= settings.STRONG_BUY_THRESHOLD:
        return "strong"
    if score >= settings.BUY_THRESHOLD:
        return "buy"
    return "watch"


def accent_panel(score: float) -> str:
    """Extract panel_accent from the real _accent() tuple."""
    return _accent(score)[2]


# ---------------------------------------------------------------------------
# 1. _accent() reads settings – not hardcoded values
# ---------------------------------------------------------------------------


class TestAccentReadsSettings:
    """_accent() must delegate to settings thresholds."""

    def test_default_strong_buy_threshold(self):
        assert settings.STRONG_BUY_THRESHOLD == 48

    def test_default_buy_threshold(self):
        assert settings.BUY_THRESHOLD == 20

    def test_accent_at_strong_buy_threshold_is_positive(self):
        _, _, panel = _accent(settings.STRONG_BUY_THRESHOLD)
        assert panel == "positive"

    def test_accent_below_strong_buy_is_primary(self):
        _, _, panel = _accent(settings.STRONG_BUY_THRESHOLD - 1)
        assert panel == "primary"

    def test_accent_at_buy_threshold_is_primary(self):
        _, _, panel = _accent(settings.BUY_THRESHOLD)
        assert panel == "primary"

    def test_accent_below_buy_threshold_is_danger(self):
        _, _, panel = _accent(settings.BUY_THRESHOLD - 1)
        assert panel == "danger"


# ---------------------------------------------------------------------------
# 2. Grouping mirror matches _accent() band semantics
# ---------------------------------------------------------------------------


class TestGroupAccentAlignment:
    """For every representative score, group and accent must agree on the band."""

    @pytest.mark.parametrize(
        "score",
        [100, 49, 48, 47, 21, 20, 19, 8, 0, -8, -20, -48, -100],
    )
    def test_group_and_accent_agree(self, score: float):
        group = classify_group(score)
        panel = accent_panel(score)

        if group == "strong":
            assert panel == "positive", f"score={score}"
        elif group == "buy":
            assert panel == "primary", f"score={score}"
        else:
            assert panel == "danger", f"score={score}"


# ---------------------------------------------------------------------------
# 3. Boundary values – off-by-one
# ---------------------------------------------------------------------------


class TestBoundaries:
    """threshold, threshold-1, threshold+1 for both STRONG_BUY and BUY."""

    @pytest.mark.parametrize(
        "score, expected_group",
        [
            (48, "strong"),  # exactly STRONG_BUY_THRESHOLD
            (47, "buy"),  # one below
            (49, "strong"),  # one above
            (20, "buy"),  # exactly BUY_THRESHOLD
            (19, "watch"),  # one below
            (21, "buy"),  # one above
        ],
    )
    def test_group_boundary(self, score, expected_group):
        assert classify_group(score) == expected_group

    @pytest.mark.parametrize(
        "score, expected_panel",
        [
            (48, "positive"),  # exactly STRONG_BUY_THRESHOLD
            (47, "primary"),  # one below
            (49, "positive"),  # one above
            (20, "primary"),  # exactly BUY_THRESHOLD
            (19, "danger"),  # one below
            (21, "primary"),  # one above
        ],
    )
    def test_accent_boundary(self, score, expected_panel):
        assert accent_panel(score) == expected_panel


# ---------------------------------------------------------------------------
# 4. Dynamic threshold overrides
# ---------------------------------------------------------------------------


class TestDynamicThresholds:
    """Override thresholds → grouping and accent adapt, then restore."""

    def test_override_changes_grouping(self):
        with settings.override(STRONG_BUY_THRESHOLD=60, BUY_THRESHOLD=30):
            assert classify_group(60) == "strong"
            assert classify_group(59) == "buy"
            assert classify_group(30) == "buy"
            assert classify_group(29) == "watch"

    def test_override_changes_accent(self):
        with settings.override(STRONG_BUY_THRESHOLD=60, BUY_THRESHOLD=30):
            assert accent_panel(60) == "positive"
            assert accent_panel(59) == "primary"
            assert accent_panel(30) == "primary"
            assert accent_panel(29) == "danger"

    def test_override_restores_original(self):
        orig_strong = settings.STRONG_BUY_THRESHOLD
        orig_buy = settings.BUY_THRESHOLD

        with settings.override(STRONG_BUY_THRESHOLD=99, BUY_THRESHOLD=50):
            pass

        assert settings.STRONG_BUY_THRESHOLD == orig_strong
        assert settings.BUY_THRESHOLD == orig_buy

    def test_consistency_after_arbitrary_override(self):
        with settings.override(STRONG_BUY_THRESHOLD=35, BUY_THRESHOLD=15):
            for score in [100, 35, 34, 15, 14, 0, -50]:
                group = classify_group(score)
                panel = accent_panel(score)

                if group == "strong":
                    assert panel == "positive", f"score={score}"
                elif group == "buy":
                    assert panel == "primary", f"score={score}"
                else:
                    assert panel == "danger", f"score={score}"


# ---------------------------------------------------------------------------
# 5. Full-range exhaustive coverage
# ---------------------------------------------------------------------------


class TestFullRange:
    """Every integer -100..100 maps to exactly one group and one accent."""

    def test_all_scores_map_to_valid_group(self):
        valid = {"strong", "buy", "watch"}
        for score in range(-100, 101):
            assert classify_group(score) in valid, f"score={score}"

    def test_all_scores_map_to_valid_accent(self):
        valid = {"positive", "primary", "danger"}
        for score in range(-100, 101):
            assert accent_panel(score) in valid, f"score={score}"

    def test_groups_mutually_exclusive(self):
        for score in range(-100, 101):
            count = 0
            if score >= settings.STRONG_BUY_THRESHOLD:
                count += 1
            if settings.BUY_THRESHOLD <= score < settings.STRONG_BUY_THRESHOLD:
                count += 1
            if score < settings.BUY_THRESHOLD:
                count += 1
            assert count == 1, f"score={score} matched {count} groups"
