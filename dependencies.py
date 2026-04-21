"""Dependency wiring helpers for CLI and runtime entry points."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional

from config import settings
from backtest import Backtester
from data_fetcher import BISTDataFetcher
from db import DataAccess
from notifier import TelegramNotifier
from strategy import StrategyEngine


@dataclass(frozen=True)
class AppContainer:
    fetcher: BISTDataFetcher
    engine: StrategyEngine
    notifier: TelegramNotifier
    db: DataAccess
    paper_trade_fetcher: BISTDataFetcher
    backtester_factory: Callable[[], Backtester]


def build_app_container(
    fetcher: Optional[BISTDataFetcher] = None,
    engine: Optional[StrategyEngine] = None,
    notifier: Optional[TelegramNotifier] = None,
    db: Optional[DataAccess] = None,
    paper_trade_fetcher: Optional[BISTDataFetcher] = None,
    backtester_factory: Optional[Callable[[], Backtester]] = None,
) -> AppContainer:
    runtime_fetcher = fetcher or BISTDataFetcher()
    runtime_engine = engine or StrategyEngine()
    runtime_notifier = notifier or TelegramNotifier()
    runtime_db = db or DataAccess()
    runtime_paper_trade_fetcher = paper_trade_fetcher or BISTDataFetcher()
    runtime_backtester_factory = backtester_factory or (
        lambda: Backtester(initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0))
    )

    return AppContainer(
        fetcher=runtime_fetcher,
        engine=runtime_engine,
        notifier=runtime_notifier,
        db=runtime_db,
        paper_trade_fetcher=runtime_paper_trade_fetcher,
        backtester_factory=runtime_backtester_factory,
    )


@lru_cache(maxsize=1)
def get_default_container() -> AppContainer:
    """Return the shared default container for runtime entry points."""
    return build_app_container()
