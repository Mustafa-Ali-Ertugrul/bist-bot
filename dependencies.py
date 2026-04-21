"""Dependency wiring helpers for CLI and runtime entry points."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional

from config import settings
from backtest import Backtester
from data_fetcher import BISTDataFetcher
from db import DataAccess
from execution.algolab_broker import AlgoLabBroker, AlgoLabCredentials
from execution.base import BaseExecutionProvider
from execution.paper_broker import PaperBroker
from notifier import TelegramNotifier
from strategy import StrategyEngine


@dataclass(frozen=True)
class AppContainer:
    fetcher: BISTDataFetcher
    engine: StrategyEngine
    notifier: TelegramNotifier
    db: DataAccess
    broker: BaseExecutionProvider
    paper_trade_fetcher: BISTDataFetcher
    backtester_factory: Callable[[], Backtester]


def build_app_container(
    fetcher: Optional[BISTDataFetcher] = None,
    engine: Optional[StrategyEngine] = None,
    notifier: Optional[TelegramNotifier] = None,
    db: Optional[DataAccess] = None,
    broker: Optional[BaseExecutionProvider] = None,
    paper_trade_fetcher: Optional[BISTDataFetcher] = None,
    backtester_factory: Optional[Callable[[], Backtester]] = None,
) -> AppContainer:
    runtime_fetcher = fetcher or BISTDataFetcher()
    runtime_engine = engine or StrategyEngine()
    runtime_notifier = notifier or TelegramNotifier()
    runtime_db = db or DataAccess()
    settings.validate_broker_config()
    runtime_broker = broker or _build_broker()
    runtime_paper_trade_fetcher = paper_trade_fetcher or BISTDataFetcher()
    runtime_backtester_factory = backtester_factory or (
        lambda: Backtester(initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0))
    )

    return AppContainer(
        fetcher=runtime_fetcher,
        engine=runtime_engine,
        notifier=runtime_notifier,
        db=runtime_db,
        broker=runtime_broker,
        paper_trade_fetcher=runtime_paper_trade_fetcher,
        backtester_factory=runtime_backtester_factory,
    )


def _build_broker() -> BaseExecutionProvider:
    if settings.BROKER_PROVIDER == "algolab":
        return AlgoLabBroker(
            AlgoLabCredentials(
                api_key=settings.ALGOLAB_API_KEY,
                username=settings.ALGOLAB_USERNAME,
                password=settings.ALGOLAB_PASSWORD,
                otp_code=settings.ALGOLAB_OTP_CODE or None,
            ),
            dry_run=settings.ALGOLAB_DRY_RUN,
        )
    return PaperBroker(initial_cash=getattr(settings, "INITIAL_CAPITAL", 8500.0))


@lru_cache(maxsize=1)
def get_default_container() -> AppContainer:
    """Return the shared default container for runtime entry points."""
    return build_app_container()
