"""Point-in-time universe resolution tests."""

from __future__ import annotations

from datetime import date

from bist_bot.data.bist100 import BIST100_2024_01_01, BIST100_TICKERS
from bist_bot.data.universe import get_universe_for_date


def test_snapshot_universe_is_full_bist100() -> None:
    """Snapshot'lar stub değil; tam 100 üyeli, doğrulanmış evreni taşır."""
    assert len(BIST100_TICKERS) == 100
    assert len(set(BIST100_TICKERS)) == 100
    assert BIST100_2024_01_01 == BIST100_TICKERS


def test_get_universe_for_date_returns_matching_snapshot():
    universe = get_universe_for_date(date(2024, 6, 1), current_universe=["CURRENT.IS"])

    assert universe == BIST100_2024_01_01


def test_get_universe_for_date_falls_back_to_current_universe(caplog):
    with caplog.at_level("WARNING"):
        universe = get_universe_for_date(
            date(2020, 1, 1), current_universe=["CURRENT.IS", "LEGACY.IS"]
        )

    assert universe == ["CURRENT.IS", "LEGACY.IS"]
    assert "Historical universe snapshot missing" in caplog.text
