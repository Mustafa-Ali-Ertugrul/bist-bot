"""Faz 1 market-data layer: universe, daily bars, fundamentals (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.db import DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services import daily_bar_service as service_module
from bist_bot.services.daily_bar_service import DailyBarService


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "market.db"))
    manager.initialize()
    return MarketDataRepository(manager)


@pytest.fixture(autouse=True)
def _no_benchmark_network(monkeypatch):
    """run_daily now also syncs XU100; tests must never hit the vendor."""
    monkeypatch.setattr(
        service_module.isyatirim,
        "fetch_index_daily",
        lambda *args, **kwargs: pd.DataFrame(columns=["value"]),
    )


def _frame(rows: list[tuple[str, float, float | None]]) -> pd.DataFrame:
    """(date, adj_close, close_raw) -> vendor-shaped frame."""
    index = pd.to_datetime([row[0] for row in rows])
    return pd.DataFrame(
        {
            "adj_close": [row[1] for row in rows],
            "close_raw": [row[2] for row in rows],
            "mcap": [1_000_000.0 for _ in rows],
            "volume_tl": [500_000.0 for _ in rows],
            "high": [row[1] * 1.02 for row in rows],
            "low": [row[1] * 0.98 for row in rows],
        },
        index=index,
    )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def test_write_bars_is_idempotent(repo: MarketDataRepository) -> None:
    bars = [
        DailyBar(date=date(2026, 1, 5), close=10.0, volume_tl=100.0),
        DailyBar(date=date(2026, 1, 6), close=10.5, volume_tl=110.0),
    ]
    assert repo.write_bars("THYAO.IS", bars, source="isyatirim") == 2
    assert repo.write_bars("THYAO.IS", bars, source="isyatirim") == 2

    assert repo.bar_count() == 2
    assert repo.latest_bar_date("THYAO.IS") == date(2026, 1, 6)


def test_write_bars_keeps_rows_outside_the_replaced_window(repo: MarketDataRepository) -> None:
    repo.write_bars(
        "THYAO.IS",
        [
            DailyBar(date=date(2026, 1, 5), close=10.0),
            DailyBar(date=date(2026, 1, 6), close=10.5),
            DailyBar(date=date(2026, 1, 7), close=11.0),
        ],
        source="isyatirim",
    )
    repo.write_bars(
        "THYAO.IS",
        [DailyBar(date=date(2026, 1, 6), close=99.0)],
        source="isyatirim",
    )
    bars = repo.get_bars("THYAO.IS")
    assert [bar.date for bar in bars] == [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    assert bars[1].close == 99.0


def test_bonus_issue_keeps_both_series_instead_of_skipping(repo: MarketDataRepository) -> None:
    """Adjacent bars can move >15% on the raw series (bonus issue); both are stored."""
    frame = _frame(
        [
            ("2026-05-11", 100.0, 100.0),
            ("2026-05-12", 50.0, 200.0),
        ]
    )
    bars = service_module.frames_to_bars(frame)
    repo.write_bars("XYZ.IS", bars, source="isyatirim")

    stored = repo.get_bars("XYZ.IS")
    assert len(stored) == 2, "the symbol must not be dropped on an adjustment gap"
    assert stored[1].close == 50.0
    assert stored[1].close_raw == 200.0


def test_universe_refresh_marks_missing_codes_inactive(repo: MarketDataRepository) -> None:
    repo.upsert_instruments(
        [
            Instrument(code="THYAO", ticker="THYAO.IS", name="Türk Hava Yolları", sector="Ulaşım"),
            Instrument(code="GARAN", ticker="GARAN.IS", name="Garanti", sector="Bankacılık"),
        ]
    )
    assert {item.code for item in repo.list_active_instruments()} == {"THYAO", "GARAN"}

    repo.upsert_instruments(
        [Instrument(code="THYAO", ticker="THYAO.IS", name="Türk Hava Yolları", sector="Ulaşım")]
    )
    assert [item.code for item in repo.list_active_instruments()] == ["THYAO"]
    assert len(repo.list_instruments()) == 2, "delisted codes keep their row and history"


def test_fundamentals_roundtrip(repo: MarketDataRepository) -> None:
    written = repo.write_statements(
        "THYAO.IS",
        {"2026/06": {"2O": 100.0, "3Z": 20.0}, "2026/03": {"3C": 80.0}},
    )
    assert written == 3
    # Re-writing one period replaces only that period.
    repo.write_statements("THYAO.IS", {"2026/06": {"2O": 111.0}})
    stored = repo.get_latest_statements("THYAO.IS")
    assert stored["2026/06"] == {"2O": 111.0}
    assert stored["2026/03"] == {"3C": 80.0}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _instrument(code: str = "THYAO") -> Instrument:
    return Instrument(code=code, ticker=f"{code}.IS", name=code, sector="Test")


def test_dates_for_full_history_and_incremental(repo: MarketDataRepository) -> None:
    with settings.override(DAILY_BARS_START_DATE="2016-01-01", DAILY_BARS_INITIAL_LOOKBACK_DAYS=30):
        service = DailyBarService(repo)
        start, end = service.dates_for(_instrument(), as_of=date(2026, 10, 21), full_history=True)
        assert start == date(2016, 1, 1) and end == date(2026, 10, 21)

        start, end = service.dates_for(_instrument(), as_of=date(2026, 10, 21), full_history=False)
        assert start == date(2026, 9, 21)

        repo.write_bars(
            "THYAO.IS", [DailyBar(date=date(2026, 10, 20), close=1.0)], source="isyatirim"
        )
        start, _ = service.dates_for(_instrument(), as_of=date(2026, 10, 21), full_history=False)
        assert start == date(2026, 10, 21)


def test_run_daily_writes_only_active_symbols(repo: MarketDataRepository, monkeypatch) -> None:
    repo.upsert_instruments(
        [
            _instrument("THYAO"),
            _instrument("GARAN"),
            _instrument("OLDCO"),
        ]
    )

    def fake_fetch(code, start, end, session):
        return _frame([("2026-10-20", 10.0, 10.0)])

    monkeypatch.setattr(service_module.isyatirim, "fetch_daily", fake_fetch)
    # Universe refresh is skipped: the stored list is non-empty.
    monkeypatch.setattr(
        service_module.isyatirim,
        "fetch_universe",
        lambda *a, **k: pytest.fail("universe must not be refreshed when rows exist"),
    )

    with settings.override(
        DAILY_BARS_ENABLED=True,
        DAILY_BARS_MAX_WORKERS=1,
        DAILY_BARS_REQUEST_DELAY_SECONDS=0.0,
        DAILY_BARS_INITIAL_LOOKBACK_DAYS=5,
    ):
        service = DailyBarService(repo)
        report = service.run_daily(as_of=date(2026, 10, 21))

    assert report.symbols == 3
    assert report.written == 3
    assert report.failed == 0


def test_run_daily_reports_vendor_failure_without_aborting(
    repo: MarketDataRepository, monkeypatch
) -> None:
    repo.upsert_instruments([_instrument("THYAO"), _instrument("GARAN")])

    def fake_fetch(code, start, end, session):
        if code == "GARAN":
            raise RuntimeError("vendor down")
        return _frame([("2026-10-20", 10.0, 10.0)])

    monkeypatch.setattr(service_module.isyatirim, "fetch_daily", fake_fetch)

    with settings.override(
        DAILY_BARS_MAX_WORKERS=1,
        DAILY_BARS_REQUEST_DELAY_SECONDS=0.0,
        DAILY_BARS_INITIAL_LOOKBACK_DAYS=5,
    ):
        report = DailyBarService(repo).run_daily(as_of=date(2026, 10, 21))

    assert report.failed == 1
    assert report.written == 1
    assert report.errors and report.errors[0].startswith("GARAN")


def test_run_if_due_is_flag_and_time_gated(repo: MarketDataRepository) -> None:
    repo.upsert_instruments([_instrument("THYAO")])
    late = datetime(2026, 10, 20, 23, 0, tzinfo=UTC)

    with settings.override(DAILY_BARS_ENABLED=False):
        assert DailyBarService(repo).run_if_due(late) is False

    with settings.override(DAILY_BARS_ENABLED=True):
        service = DailyBarService(repo)
        # 2026-10-20 is a Tuesday; before the close nothing runs.
        assert service.run_if_due(datetime(2026, 10, 20, 9, 0, tzinfo=UTC)) is False
