"""Faz 2: run the screen library over stored bars and persist the results.

Runs after the daily bar sync (never inside it) and is failure-isolated: a
broken screen must not stop the other screens or the market-data job.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.market_data_repository import DailyBar, MarketDataRepository
from bist_bot.market_calendar import is_bist_holiday, session_eod_datetime
from bist_bot.notifier import TR
from bist_bot.services.stock_profile_service import snapshot_row
from bist_bot.strategy.scans import (
    SCANS,
    FundamentalContext,
    ScanDefinition,
    bars_until,
)

logger = get_logger(__name__, component="screens")


@dataclass
class ScreenReport:
    as_of: date
    symbols: int = 0
    screens: int = 0
    hits: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    snapshots: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "symbols": self.symbols,
            "screens": self.screens,
            "hits": self.hits,
            "failed": self.failed,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "snapshots": self.snapshots,
        }


class ScanLibraryService:
    def __init__(
        self,
        repository: MarketDataRepository,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or default_settings
        self._last_run_date: date | None = None

    def run(self, *, as_of: date | None = None) -> ScreenReport:
        started = time.monotonic()
        target = as_of or datetime.now(TR).date()
        report = ScreenReport(as_of=target)

        enabled_fundamental = bool(getattr(self.settings, "SCREEN_FUNDAMENTAL_SCANS_ENABLED", True))
        screens: list[ScanDefinition] = [
            scan for scan in SCANS if scan.kind in {"technical", "temettu"} or enabled_fundamental
        ]
        bar_limit = max(40, int(getattr(self.settings, "SCREEN_SCANS_BARS_LIMIT", 400)))

        instruments = self.repository.list_active_instruments()
        statements = self.repository.get_all_statements() if enabled_fundamental else {}
        dividends = self.repository.dividend_sums(since=target - timedelta(days=365))
        report.symbols = len(instruments)

        results: dict[str, list[tuple[str, float, str]]] = {scan.code: [] for scan in screens}
        snapshots: list[dict[str, object]] = []

        for instrument in instruments:
            bars: list[DailyBar] = bars_until(
                self.repository.get_bars(instrument.ticker, end=target, limit=bar_limit),
                target,
            )
            if not bars:
                continue
            row = snapshot_row(
                instrument.ticker,
                bars,
                statements.get(instrument.ticker, {}),
                dividend_per_share=dividends.get(instrument.ticker),
            )
            if row is not None:
                snapshots.append(row)
            context = FundamentalContext(
                statements=statements.get(instrument.ticker, {}),
                market_cap_tl=bars[-1].market_cap_tl,
                dividend_yield_pct=row.get("dividend_yield_pct") if row else None,
            )
            for scan in screens:
                try:
                    hit = scan.rule(bars, target, context)
                except Exception as exc:  # one broken screen/symbol must not stop the rest
                    label = f"{scan.code}:{instrument.code}:{type(exc).__name__}"
                    if len(report.failed) < 10:
                        report.failed.append(label)
                    logger.warning("screen_rule_failed", error_type=type(exc).__name__)
                    continue
                if hit is not None:
                    results[scan.code].append((instrument.ticker, hit.value, hit.detail))

        for scan in screens:
            rows = results[scan.code]
            self.repository.replace_scan_results(scan.code, target, rows)
            report.hits[scan.code] = len(rows)

        self.repository.write_snapshots(target, snapshots)
        report.snapshots = len(snapshots)

        # Fresh screen hits change the scorecard's input set.
        clearer = getattr(self.repository, "clear_scorecard_cache", None)
        if clearer is not None:
            try:
                clearer()
            except Exception as exc:  # cache invalidation must not fail the scan
                logger.warning("scorecard_cache_clear_failed", error_type=type(exc).__name__)

        report.screens = len(screens)
        report.elapsed_seconds = time.monotonic() - started
        logger.info("screens_completed", **report.as_dict())
        return report

    def run_if_due(self, now: datetime) -> bool:
        """Run once per trading day, only after that session's bars exist."""
        if not bool(getattr(self.settings, "SCREEN_SCANS_ENABLED", False)):
            return False
        today = now.date()
        if self._last_run_date == today:
            return False
        if is_bist_holiday(today):
            return False
        if now < session_eod_datetime(today):
            return False
        if self.repository.latest_market_date() != today:
            logger.info("screens_skipped_no_bars", as_of=today.isoformat())
            return False
        try:
            self.run(as_of=today)
        except Exception as exc:
            logger.error("screens_run_failed", error_type=type(exc).__name__, error=str(exc))
            return False
        self._last_run_date = today
        return True
