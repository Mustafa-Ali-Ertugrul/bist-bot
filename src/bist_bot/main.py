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
    scheduler = MarketScheduler(scanner, container.notifier, settings=settings)
    order_tracker = OrderTracker(container.broker, container.db)

    def shutdown(signum, frame):
        _ = signum, frame
        logger.info("shutdown_requested")
        scheduler.running = False
        order_tracker.stop()

    import signal as _signal

    _signal.signal(_signal.SIGINT, shutdown)

    if "--once" in sys.argv:
        scanner.scan_once()
    elif "--backtest" in sys.argv:
        run_backtest(container.fetcher)
    elif "--dashboard" in sys.argv:
        app = create_default_dashboard_app(container)
        app.run(
            host="0.0.0.0",
            port=settings.FLASK_PORT,
            debug=False,
            use_reloader=settings.FLASK_DEBUG,
        )
    elif "--worker" in sys.argv:
        order_tracker.start()
        scheduler.run_loop()
    else:
        order_tracker.start()
        app = create_default_dashboard_app(container)
        t = Thread(
            target=lambda: app.run(
                host="0.0.0.0", port=settings.FLASK_PORT, debug=False, use_reloader=False
            ),
            daemon=True,
        )
        t.start()
        logger.info("dashboard_started", port=settings.FLASK_PORT)
        scheduler.run_loop()


if __name__ == "__main__":
    main()
