"""Faz 1: end-of-day market data ingestion (universe, daily bars, fundamentals).

Runs after the session close, separately from the EOD position pass: a vendor
outage must never block closing positions. Everything is idempotent, so a
re-run of the same session replaces rows instead of duplicating them.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.data import isyatirim
from bist_bot.data.market_source import MarketDataSource, build_market_source
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.market_calendar import is_bist_holiday, session_eod_datetime
from bist_bot.notifier import TR

logger = get_logger(__name__, component="market_data")


@dataclass
class SyncReport:
    """Outcome of one ingestion run, safe to log or print."""

    as_of: date
    symbols: int = 0
    written: int = 0
    empty: int = 0
    failed: int = 0
    universe: int = 0
    fundamentals: int = 0
    benchmarks: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "symbols": self.symbols,
            "written": self.written,
            "empty": self.empty,
            "failed": self.failed,
            "universe": self.universe,
            "fundamentals": self.fundamentals,
            "benchmarks": self.benchmarks,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "errors": self.errors,
        }


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(isyatirim.HEADERS)
    return session


def frames_to_bars(frame: pd.DataFrame) -> list[DailyBar]:
    bars: list[DailyBar] = []
    for timestamp, row in frame.iterrows():
        close = row.get("adj_close")
        if close is None or pd.isna(close):
            continue
        bars.append(
            DailyBar(
                date=timestamp.date() if hasattr(timestamp, "date") else timestamp,
                close=float(close),
                close_raw=_optional(row.get("close_raw")),
                high=_optional(row.get("high")),
                low=_optional(row.get("low")),
                volume_tl=_optional(row.get("volume_tl")),
                market_cap_tl=_optional(row.get("mcap")),
            )
        )
    return bars


def _optional(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


class DailyBarService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
        source: MarketDataSource | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings
        self.source = source or build_market_source(self.settings)
        self._last_run_date: date | None = None
        self._last_fundamentals_at: datetime | None = None
        self._last_universe_refresh: date | None = None

    # ------------------------------------------------------------------
    # Universe
    # ------------------------------------------------------------------
    def refresh_universe(self, *, force: bool = False) -> int:
        today = datetime.now(TR).date()
        refresh_days = max(1, int(getattr(self.settings, "DAILY_BARS_UNIVERSE_REFRESH_DAYS", 7)))
        if (
            not force
            and self._last_universe_refresh is not None
            and (today - self._last_universe_refresh).days < refresh_days
        ):
            return 0
        session = _new_session()
        rows = self.source.fetch_universe(session)
        if not rows:
            logger.warning("universe_refresh_empty")
            return 0
        instruments = [
            Instrument(
                code=row["code"],
                ticker=f"{row['code']}.IS",
                name=row.get("name", ""),
                sector=row.get("sector") or None,
            )
            for row in rows
        ]
        written = self.repository.upsert_instruments(instruments)
        self._last_universe_refresh = today
        logger.info("universe_refreshed", count=written)
        return written

    # ------------------------------------------------------------------
    # Daily bars
    # ------------------------------------------------------------------
    def sync_symbol(
        self,
        instrument: Instrument,
        *,
        start: date,
        end: date,
        session: requests.Session | None = None,
    ) -> int:
        session = session or _new_session()
        frame = self.source.fetch_daily(instrument.code, start, end, session)
        bars = frames_to_bars(frame)
        return self.repository.write_bars(
            instrument.ticker,
            bars,
            source=str(getattr(self.settings, "DAILY_BARS_SOURCE", "isyatirim")),
        )

    def dates_for(
        self, instrument: Instrument, *, as_of: date, full_history: bool
    ) -> tuple[date, date]:
        latest = self.repository.latest_bar_date(instrument.ticker)
        if latest is not None:
            return latest + timedelta(days=1), as_of
        if full_history:
            configured = str(getattr(self.settings, "DAILY_BARS_START_DATE", "2016-01-01"))
            try:
                start = date.fromisoformat(configured)
            except ValueError:
                start = as_of - timedelta(days=365)
            return start, as_of
        lookback = max(1, int(getattr(self.settings, "DAILY_BARS_INITIAL_LOOKBACK_DAYS", 30)))
        return as_of - timedelta(days=lookback), as_of

    def run_daily(
        self,
        *,
        as_of: date | None = None,
        full_history: bool = False,
        with_fundamentals: bool | None = None,
        max_symbols: int | None = None,
    ) -> SyncReport:
        """Sync every active instrument. ``full_history`` is for the backfill script."""
        started = time.monotonic()
        target = as_of or datetime.now(TR).date()
        report = SyncReport(as_of=target)

        instruments = self.repository.list_active_instruments()
        if not instruments:
            report.universe = self.refresh_universe(force=True)
            instruments = self.repository.list_active_instruments()
        if max_symbols is not None:
            instruments = instruments[: max(0, max_symbols)]
        report.symbols = len(instruments)
        if not instruments:
            report.elapsed_seconds = time.monotonic() - started
            logger.warning("daily_bars_no_universe", as_of=target.isoformat())
            return report

        delay = max(0.0, float(getattr(self.settings, "DAILY_BARS_REQUEST_DELAY_SECONDS", 0.2)))
        workers = max(1, int(getattr(self.settings, "DAILY_BARS_MAX_WORKERS", 2)))

        def _one(instrument: Instrument) -> tuple[int, str | None]:
            start, end = self.dates_for(instrument, as_of=target, full_history=full_history)
            if start > end:
                return 0, None
            session = _new_session()
            try:
                written = self.sync_symbol(instrument, start=start, end=end, session=session)
            except Exception as exc:  # vendor errors must not abort the batch
                return 0, f"{instrument.code}:{type(exc).__name__}"
            finally:
                if delay:
                    time.sleep(delay)
            return written, None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for written, error in pool.map(_one, instruments):
                if error is not None:
                    report.failed += 1
                    if len(report.errors) < 10:
                        report.errors.append(error)
                    continue
                if written:
                    report.written += written
                else:
                    report.empty += 1

        if with_fundamentals is None:
            with_fundamentals = bool(getattr(self.settings, "DAILY_FUNDAMENTALS_ENABLED", False))
        if with_fundamentals:
            report.fundamentals = self.sync_fundamentals(instruments, as_of=target)

        report.benchmarks = self.sync_benchmarks(as_of=target, full_history=full_history)

        # New bars change forward returns, so any stored scorecard is stale.
        if report.written or report.benchmarks:
            self._invalidate_scorecard_cache()

        report.elapsed_seconds = time.monotonic() - started
        logger.info("daily_bars_sync_completed", **report.as_dict())
        return report

    def _invalidate_scorecard_cache(self) -> None:
        clearer = getattr(self.repository, "clear_scorecard_cache", None)
        if clearer is None:
            return
        try:
            cleared = int(clearer())
        except Exception as exc:  # cache invalidation must never fail a sync
            logger.warning("scorecard_cache_clear_failed", error_type=type(exc).__name__)
            return
        if cleared:
            logger.info("scorecard_cache_cleared", rows=cleared)

    # ------------------------------------------------------------------
    # Benchmarks (Faz 5)
    # ------------------------------------------------------------------
    def sync_benchmarks(self, *, as_of: date, full_history: bool) -> int:
        """Store the XU100 series used by the portfolio comparison."""
        latest = self.repository.latest_benchmark_date("XU100")
        if latest is not None:
            start = latest + timedelta(days=1)
        elif full_history:
            configured = str(getattr(self.settings, "DAILY_BARS_START_DATE", "2016-01-01"))
            try:
                start = date.fromisoformat(configured)
            except ValueError:
                start = as_of - timedelta(days=365)
        else:
            lookback = max(1, int(getattr(self.settings, "DAILY_BARS_INITIAL_LOOKBACK_DAYS", 30)))
            start = as_of - timedelta(days=lookback)
        if start > as_of:
            return 0
        session = _new_session()
        proxy = str(getattr(self.settings, "BENCHMARK_PROXY_TICKER", "THYAO"))
        try:
            frame = self.source.fetch_index_daily(session, start, as_of, proxy)
        except Exception as exc:
            logger.warning("benchmark_fetch_failed", error_type=type(exc).__name__)
            return 0
        rows = [
            (timestamp.date() if hasattr(timestamp, "date") else timestamp, float(value))
            for timestamp, value in frame.get("value", pd.Series(dtype=float)).items()
        ]
        return self.repository.write_benchmark_bars("XU100", rows, source="isyatirim")

    # ------------------------------------------------------------------
    # Fundamentals
    # ------------------------------------------------------------------
    def sync_fundamentals(
        self,
        instruments: list[Instrument],
        *,
        as_of: date | None = None,
    ) -> int:
        target = as_of or datetime.now(TR).date()
        quarters = max(4, int(getattr(self.settings, "DAILY_FUNDAMENTALS_QUARTERS", 12)))
        periods = self.source.published_quarters(target, quarters)
        delay = max(0.0, float(getattr(self.settings, "DAILY_BARS_REQUEST_DELAY_SECONDS", 0.2)))
        written = 0
        for instrument in instruments:
            session = _new_session()
            try:
                statements = self.source.fetch_statements(instrument.code, periods, session)
            except Exception as exc:
                logger.warning(
                    "fundamentals_fetch_failed",
                    ticker=instrument.ticker,
                    error_type=type(exc).__name__,
                )
                statements = {}
            written += self.repository.write_statements(instrument.ticker, statements)
            if delay:
                time.sleep(delay)
        logger.info("fundamentals_sync_completed", written=written, symbols=len(instruments))
        return written

    # ------------------------------------------------------------------
    # Scheduler entry point
    # ------------------------------------------------------------------
    def run_if_due(self, now: datetime) -> bool:
        """Run once per trading day, after the session-close delay."""
        if not bool(getattr(self.settings, "DAILY_BARS_ENABLED", False)):
            return False
        today = now.date()
        if self._last_run_date == today:
            return False
        if is_bist_holiday(today):
            return False
        # session_eod_datetime already includes EOD_CLOSE_DELAY_MINUTES.
        if now < session_eod_datetime(today):
            return False
        try:
            self.run_daily(as_of=today)
        except Exception as exc:
            logger.error("daily_bars_run_failed", error_type=type(exc).__name__, error=str(exc))
            return False
        self._last_run_date = today
        self._run_weekly_fundamentals_if_due(now)
        return True

    def _run_weekly_fundamentals_if_due(self, now: datetime) -> bool:
        """Faz P3.5: refresh fundamentals on a slow cadence when the daily run skips them."""
        if not bool(getattr(self.settings, "WEEKLY_FUNDAMENTALS_ENABLED", False)):
            return False
        if bool(getattr(self.settings, "DAILY_FUNDAMENTALS_ENABLED", False)):
            return False  # the daily pass already refreshed them
        interval = max(1, int(getattr(self.settings, "WEEKLY_FUNDAMENTALS_INTERVAL_HOURS", 168)))
        moment = now if now.tzinfo else now.replace(tzinfo=TR)
        if self._last_fundamentals_at is not None:
            elapsed = moment - self._last_fundamentals_at
            if elapsed.total_seconds() < interval * 3600:
                return False
        try:
            self.sync_fundamentals(
                self.repository.list_active_instruments(), as_of=now.date()
            )
        except Exception as exc:
            logger.error(
                "daily_fundamentals_run_failed", error_type=type(exc).__name__, error=str(exc)
            )
            return False
        self._last_fundamentals_at = moment
        return True
