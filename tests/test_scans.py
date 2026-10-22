"""Faz 2 screen definitions: look-ahead, guards, fundamentals, persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bist_bot.config.settings import settings
from bist_bot.db import DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.scan_library_service import ScanLibraryService
from bist_bot.strategy import scans
from bist_bot.strategy.scans import FundamentalContext, bars_until

AS_OF = date(2026, 10, 20)


def _bars(closes: list[float], *, volumes: list[float] | None = None) -> list[DailyBar]:
    start = AS_OF - timedelta(days=len(closes) - 1)
    out: list[DailyBar] = []
    for index, close in enumerate(closes):
        volume = volumes[index] if volumes else 1000.0
        out.append(
            DailyBar(
                date=start + timedelta(days=index),
                close=close,
                volume_tl=volume,
                market_cap_tl=1_000_000_000.0,
            )
        )
    return out


def _ctx(statements: dict[str, dict[str, float]] | None = None) -> FundamentalContext:
    return FundamentalContext(statements=statements or {}, market_cap_tl=1_000_000_000.0)


# ---------------------------------------------------------------------------
# Guards: not enough history means no hit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scan", "minimum"),
    [
        (scans.scan_rsi_dip, scans.MIN_BARS["rsi_dip"]),
        (scans.scan_sma_5_22, scans.MIN_BARS["sma_5_22"]),
        (scans.scan_sma_50_200, scans.MIN_BARS["sma_50_200"]),
        (scans.scan_volume_shock, scans.MIN_BARS["hacim_sok"]),
        (scans.scan_52w_high, scans.MIN_BARS["zirve_52h"]),
        (scans.scan_bollinger_squeeze, scans.MIN_BARS["bb_sikisma"]),
    ],
)
def test_short_history_never_fires(scan, minimum: int) -> None:
    bars = _bars([10.0] * (minimum - 1))
    assert scan(bars, AS_OF, _ctx()) is None


# ---------------------------------------------------------------------------
# Technical rules
# ---------------------------------------------------------------------------


def test_rsi_dip_fires_only_below_30() -> None:
    declining = [100.0 - index for index in range(25)]
    hit = scans.scan_rsi_dip(_bars(declining), AS_OF, _ctx())
    assert hit is not None and hit.value < 30

    rising = [10.0 + index for index in range(25)]
    assert scans.scan_rsi_dip(_bars(rising), AS_OF, _ctx()) is None


def test_sma_5_22_crosses_exactly_once() -> None:
    closes = [10.0] * 22 + [20.0]
    assert scans.scan_sma_5_22(_bars(closes), AS_OF, _ctx()) is not None

    # One day later the cross is history, not news: same series + flat bar.
    later = [*closes, 20.0]
    later_as_of = AS_OF + timedelta(days=1)
    assert scans.scan_sma_5_22(_bars(later), later_as_of, _ctx()) is None


def test_sma_50_200_golden_cross() -> None:
    closes = [10.0] * 200 + [20.0]
    assert scans.scan_sma_50_200(_bars(closes), AS_OF, _ctx()) is not None


def test_volume_shock_requires_double_the_average() -> None:
    volumes = [1000.0] * 20 + [2500.0]
    assert scans.scan_volume_shock(_bars([10.0] * 21, volumes=volumes), AS_OF, _ctx()) is not None

    volumes_flat = [1000.0] * 20 + [1500.0]
    assert scans.scan_volume_shock(_bars([10.0] * 21, volumes=volumes_flat), AS_OF, _ctx()) is None


def test_52w_high_excludes_the_current_bar() -> None:
    closes = [10.0] * 252 + [11.0]
    hit = scans.scan_52w_high(_bars(closes), AS_OF, _ctx())
    assert hit is not None and hit.value == 11.0

    # Equal to the prior high is not a breakout.
    flat = [10.0] * 253
    assert scans.scan_52w_high(_bars(flat), AS_OF, _ctx()) is None


def test_bollinger_squeeze_needs_a_narrow_current_band() -> None:
    # Volatility decays linearly: the current band is the narrowest of the window.
    decaying = [20.0 + (5.0 if index % 2 else -5.0) * (1 - index / 140) for index in range(141)]
    assert scans.scan_bollinger_squeeze(_bars(decaying), AS_OF, _ctx()) is not None

    # Volatility expands into the last bar: the current band is not narrow.
    expanding = [20.0 + (5.0 if index % 2 else -5.0) * (0.2 + index / 140) for index in range(141)]
    assert scans.scan_bollinger_squeeze(_bars(expanding), AS_OF, _ctx()) is None


# ---------------------------------------------------------------------------
# Look-ahead
# ---------------------------------------------------------------------------


def test_future_bar_cannot_change_todays_result() -> None:
    closes = [100.0 - index for index in range(25)]
    bars = _bars(closes)
    today = scans.scan_rsi_dip(bars_until(bars, AS_OF), AS_OF, _ctx())

    future = [
        *bars,
        DailyBar(date=AS_OF + timedelta(days=1), close=1.0, volume_tl=1.0),
    ]
    tomorrow_input = bars_until(future, AS_OF)
    assert tomorrow_input == bars
    assert scans.scan_rsi_dip(tomorrow_input, AS_OF, _ctx()) == today


# ---------------------------------------------------------------------------
# Fundamentals (published periods only)
# ---------------------------------------------------------------------------


def test_cheap_profitable_ignores_unpublished_annual_statement() -> None:
    statements = {"2025/12": {"3Z": 200_000_000.0}}
    bars = _bars([10.0] * 5)

    # 2025 annual is public from 2026-04-15.
    hit = scans.scan_cheap_profitable(bars, AS_OF, _ctx(statements))
    assert hit is not None and hit.value == pytest.approx(5.0)

    assert scans.scan_cheap_profitable(bars, date(2026, 3, 1), _ctx(statements)) is None


def test_cheap_profitable_skips_losses_and_expensive_names() -> None:
    bars = _bars([10.0] * 5)
    assert scans.scan_cheap_profitable(bars, AS_OF, _ctx({"2025/12": {"3Z": -1.0}})) is None
    # PE = 50
    assert scans.scan_cheap_profitable(bars, AS_OF, _ctx({"2025/12": {"3Z": 20_000_000.0}})) is None


def test_sales_growth_compares_the_same_quarter_last_year() -> None:
    statements = {
        "2026/06": {"3C": 120.0},
        "2025/06": {"3C": 100.0},
    }
    # Q2 2026 statement is public from 2026-09-15.
    hit = scans.scan_sales_growth(_bars([10.0] * 2), AS_OF, _ctx(statements))
    assert hit is not None and hit.value == pytest.approx(20.0)

    slow = {"2026/06": {"3C": 119.0}, "2025/06": {"3C": 100.0}}
    assert scans.scan_sales_growth(_bars([10.0] * 2), AS_OF, _ctx(slow)) is None


# ---------------------------------------------------------------------------
# Persistence + service
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "screens.db"))
    manager.initialize()
    return MarketDataRepository(manager)


def test_scan_results_are_idempotent(repo: MarketDataRepository) -> None:
    repo.replace_scan_results("rsi_dip", AS_OF, [("THYAO.IS", 20.0, "RSI")])
    repo.replace_scan_results("rsi_dip", AS_OF, [("THYAO.IS", 21.0, "RSI")])
    rows = repo.get_scan_results("rsi_dip", AS_OF)
    assert len(rows) == 1 and rows[0]["value"] == 21.0

    # A previous session must survive a later run.
    repo.replace_scan_results("rsi_dip", AS_OF - timedelta(days=1), [("GARAN.IS", 19.0, "RSI")])
    assert len(repo.get_scan_results("rsi_dip", AS_OF - timedelta(days=1))) == 1
    assert len(repo.get_scan_results("rsi_dip", AS_OF)) == 1


def test_service_runs_screens_and_persists_hits(repo: MarketDataRepository) -> None:
    repo.upsert_instruments(
        [Instrument(code="THYAO", ticker="THYAO.IS", name="THYAO", sector="Test")]
    )
    repo.write_bars(
        "THYAO.IS",
        _bars([100.0 - index for index in range(25)]),
        source="isyatirim",
    )
    repo.write_statements("THYAO.IS", {"2025/12": {"3Z": 200_000_000.0}})

    with settings.override(
        SCREEN_SCANS_ENABLED=True,
        SCREEN_FUNDAMENTAL_SCANS_ENABLED=True,
        SCREEN_SCANS_BARS_LIMIT=400,
    ):
        service = ScanLibraryService(repo)
        report = service.run(as_of=AS_OF)

    assert report.symbols == 1
    assert report.screens == len(scans.SCANS)
    assert report.hits["rsi_dip"] == 1
    assert report.hits["ucuz_karli"] == 1
    assert repo.get_scan_results("rsi_dip", AS_OF)


def test_run_if_due_requires_flag_bars_and_time(repo: MarketDataRepository) -> None:
    repo.upsert_instruments(
        [Instrument(code="THYAO", ticker="THYAO.IS", name="THYAO", sector="Test")]
    )
    late = datetime(AS_OF.year, AS_OF.month, AS_OF.day, 20, 0, tzinfo=UTC)

    with settings.override(SCREEN_SCANS_ENABLED=False):
        assert ScanLibraryService(repo).run_if_due(late) is False

    with settings.override(SCREEN_SCANS_ENABLED=True):
        service = ScanLibraryService(repo)
        # No bars for that session yet -> no run.
        assert service.run_if_due(late) is False
