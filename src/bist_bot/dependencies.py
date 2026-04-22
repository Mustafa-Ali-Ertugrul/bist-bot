"""Dependency wiring helpers for CLI and runtime entry points."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional

from bist_bot.config.settings import settings
from bist_bot.backtest import Backtester
from bist_bot.data.fetcher import BISTDataFetcher, BorsaIstanbulQuoteProvider, MarketDataProvider, OfficialProviderStub, YFinanceProvider
from bist_bot.db import DataAccess
from bist_bot.execution.algolab_broker import AlgoLabBroker, AlgoLabCredentials
from bist_bot.execution.base import BaseExecutionProvider
from bist_bot.execution.paper_broker import PaperBroker
from bist_bot.scanner import ScanService
from bist_bot.notifier import TelegramNotifier
from bist_bot.risk_manager import RiskManager
from bist_bot.strategy import StrategyEngine


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
    data_provider = _build_data_provider()
    quote_provider = BorsaIstanbulQuoteProvider(rate_limiter=_build_rate_limiter())
    runtime_fetcher = fetcher or BISTDataFetcher(provider=data_provider, quote_provider=quote_provider)
    runtime_notifier = notifier or TelegramNotifier()
    runtime_db = db or DataAccess()
    runtime_engine = engine or StrategyEngine(
        risk_manager=RiskManager(
            capital=getattr(settings, "INITIAL_CAPITAL", 8500.0),
            position_repository=runtime_db,
        )
    )
    settings.validate_broker_config()
    runtime_broker = broker or _build_broker()
    runtime_paper_trade_fetcher = paper_trade_fetcher or BISTDataFetcher(
        provider=_build_data_provider(),
        quote_provider=BorsaIstanbulQuoteProvider(rate_limiter=_build_rate_limiter()),
    )
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


def _build_rate_limiter():
    from bist_bot.data.fetcher import RateLimiter

    return RateLimiter()


def _build_data_provider() -> MarketDataProvider:
    provider_name = getattr(settings, "DATA_PROVIDER", "yfinance")
    if provider_name == "official_stub":
        return OfficialProviderStub()
    return YFinanceProvider(rate_limiter=_build_rate_limiter())


def build_scan_service(container: Optional[AppContainer] = None) -> ScanService:
    runtime_container = container or get_default_container()
    return ScanService(
        runtime_container.fetcher,
        runtime_container.engine,
        runtime_container.notifier,
        runtime_container.db,
        broker=runtime_container.broker,
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_default_container() -> AppContainer:
    """Return the shared default container for runtime entry points."""
    return build_app_container()
