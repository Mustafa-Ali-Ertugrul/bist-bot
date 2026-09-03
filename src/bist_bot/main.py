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
    scheduler = MarketScheduler(
        scanner,
        container.notifier,
        settings=settings,
        trading_agent=container.trading_agent,
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

        # AppContainer has no signals_repo; the report builds its own
        # SignalsRepository on the shared DatabaseManager when repo=None.
        from bist_bot.db.repositories.portfolio_repository import PortfolioRepository

        report_md = generate_daily_report(
            day=target_date,
            portfolio_repo=PortfolioRepository(container.db),
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
