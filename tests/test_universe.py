"""Point-in-time universe resolution tests."""

from __future__ import annotations

from datetime import date

from bist_bot.data.universe import get_universe_for_date


def test_get_universe_for_date_returns_matching_snapshot():
    universe = get_universe_for_date(date(2024, 6, 1), current_universe=["CURRENT.IS"])

    assert universe == ["THYAO.IS", "ASELS.IS", "GARAN.IS", "BIMAS.IS", "TUPRS.IS", "SAHOL.IS"]


def test_get_universe_for_date_falls_back_to_current_universe(caplog):
    with caplog.at_level("WARNING"):
        universe = get_universe_for_date(
            date(2020, 1, 1), current_universe=["CURRENT.IS", "LEGACY.IS"]
        )

    assert universe == ["CURRENT.IS", "LEGACY.IS"]
    assert "falling back to current universe" in caplog.text
