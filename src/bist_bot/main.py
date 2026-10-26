"""Primary runtime entry point for the bot and scheduler process."""

import sys

from bist_bot.app_logging import configure_logging, get_logger

logger = get_logger(__name__, component="main")


def main():
    """Run the CLI-oriented bot process.

    Modes:
    - default: scheduler + embedded Flask dashboard
    - --once: single scan
    - --backtest: run watchlist backtests
    - --dashboard: run only the Flask dashboard
    - --worker: run only the scanner scheduler worker
    """
    configure_logging()

    from threading import Thread

    from bist_bot.backtest_runner import run_backtest
    from bist_bot.config.settings import settings
    from bist_bot.dashboard import create_default_dashboard_app
    from bist_bot.dependencies import build_scan_service, get_default_container
    from bist_bot.execution.order_tracker import OrderTracker
    from bist_bot.scheduler import MarketScheduler

    container = get_default_container()
    scanner = build_scan_service(container)
    monthly_portfolio = None
    if settings.MONTHLY_PORTFOLIO_ENABLED:
        from bist_bot.services.monthly_portfolio_service import MonthlyPortfolioService

        monthly_portfolio = MonthlyPortfolioService(container.fetcher, container.notifier, settings)
    league = None
    if settings.LEAGUE_ENABLED:
        from bist_bot.services.league_service import LeagueService

        league = LeagueService(container.fetcher, container.notifier, settings)
    overnight = None
    if settings.OVERNIGHT_ENABLED:
        from bist_bot.services.overnight_service import OvernightService

        overnight = OvernightService(container.fetcher, container.notifier, settings)
    daily_bars = None
    if settings.DAILY_BARS_ENABLED:
        from bist_bot.services.daily_bar_service import DailyBarService

        daily_bars = DailyBarService(container.db.market_data, settings)
    screen_scans = None
    if settings.SCREEN_SCANS_ENABLED:
        from bist_bot.services.scan_library_service import ScanLibraryService

        screen_scans = ScanLibraryService(container.db.market_data, settings)
    kap_sync = None
    if settings.KAP_SYNC_ENABLED:
        from bist_bot.services.corporate_actions_service import CorporateActionsService
        from bist_bot.services.kap_service import KapService, KapSyncJob

        kap_sync = KapSyncJob(
            KapService(container.db.market_data, settings),
            CorporateActionsService(container.db.market_data, settings),
            settings,
        )
    alerts = None
    user_bot_token = settings.TELEGRAM_USER_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN
    # In-app alert history does not need Telegram: build the service when either
    # the digest or the in-app events are enabled, and only attach a notifier
    # when the Telegram digest is actually on.
    if settings.USER_DIGEST_ENABLED or getattr(settings, "IN_APP_ALERT_EVENTS_ENABLED", False):
        from bist_bot.notifier import TelegramNotifier
        from bist_bot.services.alert_digest_service import AlertDigestService

        digest_notifier = (
            TelegramNotifier(token=user_bot_token, chat_id=settings.TELEGRAM_CHAT_ID)
            if settings.USER_DIGEST_ENABLED
            else None
        )
        alerts = AlertDigestService(
            container.db.alerts,
            container.db.market_data,
            container.db.user_data,
            digest_notifier,
            settings,
        )
    if settings.TELEGRAM_LINK_POLLING_ENABLED and user_bot_token:
        from bist_bot.notifier import TelegramNotifier
        from bist_bot.services.telegram_link_poller import TelegramLinkPoller
        from bist_bot.services.telegram_link_service import TelegramLinkService

        link_notifier = TelegramNotifier(token=user_bot_token, chat_id=settings.TELEGRAM_CHAT_ID)
        link_service = TelegramLinkService(container.db.alerts, link_notifier, settings)
        TelegramLinkPoller(
            container.db.alerts, link_service, user_bot_token, settings=settings
        ).start_thread()
    scheduler = MarketScheduler(
        scanner,
        container.notifier,
        settings=settings,
        trading_agent=container.trading_agent,
        monthly_portfolio=monthly_portfolio,
        league=league,
        overnight=overnight,
        daily_bars=daily_bars,
        screen_scans=screen_scans,
        alerts=alerts,
        kap_sync=kap_sync,
    )
    order_tracker = OrderTracker(container.broker, container.db)

    def shutdown(signum, frame):
        _ = signum, frame
        logger.info(
            "shutdown_requested",
            signal="SIGINT" if signum == _signal.SIGINT else "SIGTERM",
        )
        scheduler.running = False
        order_tracker.stop()

    import signal as _signal

    # C1: docker stop SIGTERM gonderir — yakalanmazsa surec aninda olur,
    # acik tarama/DB islemi yarim kalir. SIGINT ile ayni graceful yol.
    _signal.signal(_signal.SIGINT, shutdown)
    _signal.signal(_signal.SIGTERM, shutdown)

    if "--score-correlation" in sys.argv:
        from bist_bot.reports.score_correlation import run as run_score_corr

        md = run_score_corr()
        print(md)
        return
    if "--once" in sys.argv:
        scanner.scan_once()
    elif "--daily-report" in sys.argv:
        from datetime import datetime

        from bist_bot.reports.daily_report import generate_daily_report

        target_date = None
        idx = sys.argv.index("--daily-report")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            try:
                target_date = datetime.strptime(sys.argv[idx + 1], "%Y-%m-%d").date()
            except ValueError:
                logger.error("invalid_date_format", value=sys.argv[idx + 1], expected="YYYY-MM-DD")
                print(f"Hata: Geçersiz tarih formatı '{sys.argv[idx + 1]}'. YYYY-MM-DD bekleniyor.")
                return

        # DataAccess facade'inde hazir repo'lar var: signals/portfolio.
        # Yeni DatabaseManager kurmak (ikinci engine + create_all + bootstrap)
        # ve PortfolioRepository(container.db) tip hatasi onlenir.
        report_md = generate_daily_report(
            day=target_date,
            repo=container.db.signals,
            portfolio_repo=container.db.portfolio,
        )
        print(report_md)
    elif "--backtest" in sys.argv:
        run_backtest(container.fetcher)
    elif "--dashboard" in sys.argv:
        app = create_default_dashboard_app(container)
        # nosec B104: container entrypoint; exposure via compose/Cloud Run.
        app.run(
            host="0.0.0.0",  # nosec B104
            port=settings.FLASK_PORT,
            debug=False,
            use_reloader=settings.FLASK_DEBUG,
        )
    elif "--worker" in sys.argv:
        from bist_bot.worker_http import WorkerHealthServer

        worker_http = WorkerHealthServer(
            scheduler,
            port=int(getattr(settings, "WORKER_METRICS_PORT", 9101)),
            settings=settings,
        )
        worker_http.start()
        order_tracker.start()
        try:
            scheduler.run_loop()
        finally:
            worker_http.stop()
    else:
        order_tracker.start()
        app = create_default_dashboard_app(container)
        t = Thread(
            target=lambda: app.run(
                host="0.0.0.0",  # nosec B104: container-local; see above.
                port=settings.FLASK_PORT,
                debug=False,
                use_reloader=False,
            ),
            daemon=True,
        )
        t.start()
        logger.info("dashboard_started", port=settings.FLASK_PORT)
        scheduler.run_loop()


if __name__ == "__main__":
    main()
