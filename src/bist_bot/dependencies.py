"""Dependency wiring helpers for CLI and runtime entry points."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from bist_bot.agent import TradingAgent
from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import set_gauge
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
from bist_bot.execution.algolab_broker import AlgoLabBroker, AlgoLabCredentials, AlgoLabEndpoints
from bist_bot.execution.base import BaseExecutionProvider
from bist_bot.notifier import TelegramNotifier
from bist_bot.risk import RiskManager
from bist_bot.risk.circuit_breaker import CircuitBreaker
from bist_bot.scanner import ScanService
from bist_bot.strategy import StrategyEngine

logger = get_logger(__name__, component="dependencies")


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
    trading_agent: TradingAgent | None = None


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
    _report_auto_execute_migration_state()
    # Fail closed on dangerous/inconsistent risk, score, and timeout settings.
    settings.enforce_preflight_validation()
    validation_errors = settings.validate_all()
    if validation_errors:
        # validate_all may still include provider/broker credential issues that are
        # environment-specific; log them but keep preflight hard-fail above.
        logger.warning("config_validation_errors", errors=validation_errors)
    data_provider = _build_data_provider()
    quote_provider = BorsaIstanbulQuoteProvider(rate_limiter=_build_rate_limiter())
    watchlist = list(getattr(settings, "WATCHLIST", []) or [])
    runtime_fetcher = fetcher or BISTDataFetcher(
        watchlist=watchlist if watchlist else None,
        provider=data_provider,
        quote_provider=quote_provider,
    )
    if watchlist:
        runtime_fetcher.watchlist = watchlist
    runtime_notifier = notifier or TelegramNotifier()
    runtime_db = db or DataAccess()
    runtime_engine = engine or StrategyEngine(
        risk_manager=RiskManager(
            capital=getattr(settings, "INITIAL_CAPITAL", 8500.0),
            position_repository=runtime_db,
        )
    )
    settings.validate_broker_config()
    runtime_broker = broker or _build_broker(runtime_db)
    runtime_paper_trade_fetcher = paper_trade_fetcher or BISTDataFetcher(
        watchlist=watchlist if watchlist else None,
        provider=_build_data_provider(),
        quote_provider=BorsaIstanbulQuoteProvider(rate_limiter=_build_rate_limiter()),
    )
    if watchlist:
        runtime_paper_trade_fetcher.watchlist = watchlist
    runtime_backtester_factory = backtester_factory or (
        lambda: Backtester(initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0))
    )
    runtime_circuit_breaker = circuit_breaker or CircuitBreaker(
        capital=getattr(settings, "INITIAL_CAPITAL", 8500.0)
    )

    # BUG-4 fix: wire TradingAgent when AGENT_ENABLED
    runtime_trading_agent = None
    if getattr(settings, "AGENT_ENABLED", False) or getattr(
        getattr(settings, "agent", None), "AGENT_ENABLED", False
    ):
        from bist_bot.agent.exit_service import ExitService as _ExitService
        from bist_bot.agent.position_manager import PositionManager as _PositionManager
        from bist_bot.agent.trading_agent import TradingAgent as _TradingAgent

        pos_mgr = _PositionManager(runtime_db, settings)
        exit_svc = _ExitService(broker=runtime_broker, db=runtime_db, settings=settings)
        from bist_bot.services.execution_service import ExecutionService as _ExecSvc

        exec_svc = _ExecSvc(runtime_db, broker=runtime_broker, settings=settings)
        runtime_trading_agent = _TradingAgent(
            position_manager=pos_mgr,
            exit_service=exit_svc,
            circuit_breaker=runtime_circuit_breaker,
            db=runtime_db,
            notifier=runtime_notifier,
            settings=settings,
            data_fetcher=runtime_fetcher,
            execution_service=exec_svc,
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
        trading_agent=runtime_trading_agent,
    )


def _report_auto_execute_migration_state() -> bool:
    blocked = bool(settings.AUTO_EXECUTE) and not bool(settings.AUTO_EXECUTE_ENABLED)
    set_gauge("bist_auto_execute_migration_blocked", 1.0 if blocked else 0.0)
    if blocked:
        logger.warning(
            "auto_execute_disabled_new_gate_required",
            detail=(
                "AUTO_EXECUTE=true is set, but AUTO_EXECUTE_ENABLED=false. "
                "Order execution remains disabled until the new flag is explicitly enabled."
            ),
            migration_required=True,
        )
    return blocked


def _build_broker(db: DataAccess | None = None) -> BaseExecutionProvider:
    """Build broker based on BROKER_MODE / BROKER_PROVIDER.

    - paper  → PaperBroker (simulation, immediate market fills)
    - live   → LiveBroker stub (raises NotImplementedError on submit)
    - algolab → venue adapter under execution/

    Alpaca has been removed from the project; BROKER_PROVIDER=alpaca raises
    ValueError directing users to paper mode.
    """
    mode = str(getattr(settings, "BROKER_MODE", "") or settings.BROKER_PROVIDER).lower()
    provider = str(settings.BROKER_PROVIDER).lower()

    if provider == "alpaca":
        raise ValueError("Alpaca removed; use paper")

    effective = provider if provider in {"algolab"} else mode

    if effective == "algolab":
        accounting_service = None
        if db is not None:
            from bist_bot.agent.position_manager import PositionManager
            from bist_bot.execution.reconcile_accounting import ReconcileAccountingService

            pm = PositionManager(db, settings)
            accounting_service = ReconcileAccountingService(db=db, position_manager=pm)

        algolab = AlgoLabBroker(
            AlgoLabCredentials(
                api_key=settings.ALGOLAB_API_KEY,
                username=settings.ALGOLAB_USERNAME,
                password=settings.ALGOLAB_PASSWORD,
                otp_code=settings.ALGOLAB_OTP_CODE or None,
            ),
            endpoints=AlgoLabEndpoints(
                login=settings.ALGOLAB_LOGIN_URL or None,
                verify_otp=settings.ALGOLAB_VERIFY_OTP_URL or None,
                positions=settings.ALGOLAB_POSITIONS_URL or None,
                account=settings.ALGOLAB_ACCOUNT_URL or None,
                orders=settings.ALGOLAB_ORDERS_URL or None,
                order_status=settings.ALGOLAB_ORDER_STATUS_URL or None,
                cancel_order=settings.ALGOLAB_CANCEL_ORDER_URL or None,
                open_orders=settings.ALGOLAB_OPEN_ORDERS_URL or None,
                order_history=settings.ALGOLAB_ORDER_HISTORY_URL or None,
            ),
            dry_run=settings.ALGOLAB_DRY_RUN,
            order_intents=db.order_intents if db is not None else None,
            send_client_id=settings.ALGOLAB_SEND_CLIENT_ID,
            reconcile_window_seconds=settings.ALGOLAB_RECONCILE_WINDOW_SECONDS,
            cancel_remainder=settings.ALGOLAB_RECONCILE_CANCEL_REMAINDER,
            accounting_service=accounting_service,
        )
        if not settings.ALGOLAB_DRY_RUN and settings.ALGOLAB_RECONCILE_ON_STARTUP:
            if settings.EXPECTED_INSTANCE_COUNT > 1:
                logger.warning(
                    "startup_reconcile_multi_instance",
                    detail=(
                        "Startup reconciliation runs on instance 1 without multi-instance "
                        "distributed locking; coordinate instances during startup."
                    ),
                )
            algolab.reconcile_pending_intents(background=True)
        return algolab
    if effective == "live":
        from bist_bot.execution.live import LiveBroker

        return LiveBroker(provider=provider, settings=settings)

    # Default paper path: single execution implementation (no facade indirection)
    from bist_bot.execution.paper_broker import PaperBroker as BrokerPaperBroker

    return BrokerPaperBroker(
        initial_cash=getattr(settings, "INITIAL_CAPITAL", 8500.0),
        manual_confirm=getattr(settings, "CONFIRM_LIVE_TRADING", False),
    )  # type: ignore[return-value]


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
            timeout=getattr(settings, "OFFICIAL_TIMEOUT", 8.0),
            max_retries=getattr(settings, "OFFICIAL_MAX_RETRIES", 2),
            retry_backoff=getattr(settings, "OFFICIAL_RETRY_BACKOFF_SECONDS", 0.5),
            max_retry_sleep=getattr(settings, "OFFICIAL_MAX_RETRY_SLEEP_SECONDS", 2.0),
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
