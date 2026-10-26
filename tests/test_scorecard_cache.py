"""Faz P3.4: scorecard cache behaviour."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bist_bot.db import DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.scan_scorecard_service import ScanScorecardService

D0 = date(2026, 1, 5)
D1 = date(2026, 1, 6)


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "scorecache.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    repository.upsert_instruments(
        [Instrument(code="AAA", ticker="AAA.IS", name="A", sector="Test")]
    )
    repository.write_bars(
        "AAA.IS",
        [
            DailyBar(date=D0, close=100.0, close_raw=100.0),
            DailyBar(date=D1, close=110.0, close_raw=110.0),
        ],
        source="isyatirim",
    )
    repository.write_benchmark_bars("XU100", [(D0, 1000.0), (D1, 1010.0)], source="isyatirim")
    repository.replace_scan_results("rsi_dip", D0, [("AAA.IS", 20.0, "RSI")])
    return repository


def test_first_call_writes_cache_and_second_reads_it(repo: MarketDataRepository) -> None:
    service = ScanScorecardService(repo)
    first = service.all_scorecards(horizons=(1,))
    assert first

    key = service._cache_key(None, (1,))
    stored = repo.get_scorecard_cache(key)
    assert stored is not None

    # A broken source would raise; the cached copy must be served instead.
    repo.replace_scan_results("rsi_dip", D0, [])
    second = service.all_scorecards(horizons=(1,))
    assert second == first


def test_cache_bypass_skips_stored_copy(repo: MarketDataRepository) -> None:
    service = ScanScorecardService(repo)
    service.all_scorecards(horizons=(1,))
    repo.replace_scan_results("rsi_dip", D0, [])

    fresh = service.all_scorecards(horizons=(1,), use_cache=False)
    rsi = next(item for item in fresh if item["scan_id"] == "rsi_dip")
    assert rsi["horizons"] == []


def test_expired_cache_is_recomputed(repo: MarketDataRepository) -> None:
    service = ScanScorecardService(repo)
    service.all_scorecards(horizons=(1,))
    key = service._cache_key(None, (1,))

    # Backdate the stored row, then make the source empty.
    manager = repo.manager
    stale = datetime.now(UTC) - timedelta(hours=48)
    with manager.engine.begin() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "UPDATE scorecard_cache SET computed_at = :moment WHERE cache_key = :key"
            ),
            {"moment": stale.replace(tzinfo=None), "key": key},
        )
    repo.replace_scan_results("rsi_dip", D0, [])

    recomputed = service.all_scorecards(horizons=(1,))
    rsi = next(item for item in recomputed if item["scan_id"] == "rsi_dip")
    assert rsi["horizons"] == []


def test_clear_cache_removes_rows(repo: MarketDataRepository) -> None:
    ScanScorecardService(repo).all_scorecards(horizons=(1,))
    assert repo.clear_scorecard_cache() >= 1
    assert repo.get_scorecard_cache(ScanScorecardService(repo)._cache_key(None, (1,))) is None
