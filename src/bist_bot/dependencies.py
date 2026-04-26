"""Dependency wiring helpers for CLI and runtime entry points."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from bist_bot.backtest import Backtester
from bist_bot.config.settings import settings
from bist_bot.data.fetcher import (
    BISTDataFetcher,
    BorsaIstanbulQuoteProvider,
    DataProviderRouter,
    MarketDataProvider,
    OfficialProviderStub,
    YFinanceProvider,
)
from bist_bot.data.providers import build_official_provider, resolve_official_endpoints
from bist_bot.db import DataAccess
from bist_bot.execution.algolab_broker import AlgoLabBroker, AlgoLabCredentials
from bist_bot.execution.base import BaseExecutionProvider
from bist_bot.execution.paper_broker import PaperBroker
from bist_bot.notifier import TelegramNotifier
from bist_bot.risk import RiskManager
from bist_bot.risk.circuit_breaker import CircuitBreaker
from bist_bot.scanner import ScanService
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
    circuit_breaker: CircuitBreaker


def build_app_container(
    fetcher: BISTDataFetcher | None = None,
    engine: StrategyEngine | None = None,
    notifier: TelegramNotifier | None = None,
    db: DataAccess | None = None,
    broker: BaseExecutionProvider | None = None,
    paper_trade_fetcher: BISTDataFetcher | None = None,
    backtester_factory: Callable[[], Backtester] | None = None,
    circuit_breaker: CircuitBreaker | None = None,
) -> AppContainer:
    validation_errors = settings.validate_all()
    if validation_errors:
        from bist_bot.app_logging import get_logger

        get_logger(__name__, component="dependencies").warning(
            "config_validation_errors", errors=validation_errors
        )
    data_provider = _build_data_provider()
    quote_provider = BorsaIstanbulQuoteProvider(rate_limiter=_build_rate_limiter())
    runtime_fetcher = fetcher or BISTDataFetcher(
        provider=data_provider, quote_provider=quote_provider
    )
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
    runtime_circuit_breaker = circuit_breaker or CircuitBreaker(
        capital=getattr(settings, "INITIAL_CAPITAL", 8500.0)
    )

    return AppContainer(
        fetcher=runtime_fetcher,
        engine=runtime_engine,
        notifier=runtime_notifier,
        db=runtime_db,
        broker=runtime_broker,
        paper_trade_fetcher=runtime_paper_trade_fetcher,
        backtester_factory=runtime_backtester_factory,
        circuit_breaker=runtime_circuit_breaker,
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
    return PaperBroker(
        initial_cash=getattr(settings, "INITIAL_CAPITAL", 8500.0),
        manual_confirm=getattr(settings, "CONFIRM_LIVE_TRADING", False),
    )


def _build_rate_limiter():
    from bist_bot.data.fetcher import RateLimiter

    return RateLimiter()


def _build_data_provider() -> MarketDataProvider:
    provider_name = getattr(settings, "DATA_PROVIDER", "yfinance")
    fallback_order = [
        s.strip()
        for s in getattr(settings, "DATA_PROVIDER_FALLBACK_ORDER", "").split(",")
        if s.strip()
    ]
    if provider_name == "official":
        settings.validate_data_provider_config()
        primary = build_official_provider(
            vendor=getattr(settings, "OFFICIAL_VENDOR", "generic"),
            base_url=settings.OFFICIAL_API_BASE_URL,
            api_key=settings.OFFICIAL_API_KEY,
            username=settings.OFFICIAL_USERNAME,
            password=settings.OFFICIAL_PASSWORD,
            rate_limiter=_build_rate_limiter(),
            timeout=getattr(settings, "OFFICIAL_TIMEOUT", 30.0),
            max_retries=getattr(settings, "OFFICIAL_MAX_RETRIES", 3),
            retry_backoff=getattr(settings, "OFFICIAL_RETRY_BACKOFF_SECONDS", 1.0),
            endpoints=resolve_official_endpoints(
                vendor=getattr(settings, "OFFICIAL_VENDOR", "generic"),
                auth=getattr(settings, "OFFICIAL_AUTH_ENDPOINT", "") or None,
                history=getattr(settings, "OFFICIAL_HISTORY_ENDPOINT", "") or None,
                batch=getattr(settings, "OFFICIAL_BATCH_ENDPOINT", "") or None,
                quote=getattr(settings, "OFFICIAL_QUOTE_ENDPOINT", "") or None,
                universe=getattr(settings, "OFFICIAL_UNIVERSE_ENDPOINT", "") or None,
            ),
        )
        if fallback_order:
            providers = [primary] + [_build_provider_by_name(n) for n in fallback_order]
            return DataProviderRouter(
                providers,
                failure_threshold=getattr(settings, "FAILOVER_FAILURE_THRESHOLD", 3),
                cooldown_seconds=getattr(settings, "FAILOVER_COOLDOWN_SECONDS", 60.0),
            )
        return primary
    if provider_name == "official_stub":
        return OfficialProviderStub()
    return YFinanceProvider(rate_limiter=_build_rate_limiter())


def _build_provider_by_name(name: str) -> MarketDataProvider:
    if name == "yfinance":
        return YFinanceProvider(rate_limiter=_build_rate_limiter())
    if name == "official_stub":
        return OfficialProviderStub()
    return OfficialProviderStub()


def build_scan_service(container: AppContainer | None = None) -> ScanService:
    runtime_container = container or get_default_container()
    return ScanService(
        runtime_container.fetcher,
        runtime_container.engine,
        runtime_container.notifier,
        runtime_container.db,
        broker=runtime_container.broker,
        settings=settings,
        circuit_breaker=runtime_container.circuit_breaker,
    )


@lru_cache(maxsize=1)
def get_default_container() -> AppContainer:
    """Return the shared default container for runtime entry points."""
    return build_app_container()
