"""Primary runtime entry point for the bot and scheduler process."""

import logging
import sys

from app_logging import configure_logging

logger = logging.getLogger(__name__)


def main():
    """Run the CLI-oriented bot process.

    Modes:
    - default: scheduler + embedded Flask dashboard
    - --once: single scan
    - --backtest: run watchlist backtests
    - --dashboard: run only the Flask dashboard
    """
    configure_logging()

    from dashboard import create_default_dashboard_app
    from dependencies import get_default_container
    from scanner import ScanService
    from scheduler import MarketScheduler
    from backtest_runner import run_backtest
    from threading import Thread

    from config import settings

    container = get_default_container()
    scanner = ScanService(container.fetcher, container.engine, container.notifier, container.db, settings=settings)
    scheduler = MarketScheduler(scanner, container.notifier, settings=settings)

    def shutdown(signum, frame):
        logger.info("🛑 Bot durduruluyor...")
        scheduler.running = False

    import signal as _signal
    _signal.signal(_signal.SIGINT, shutdown)

    if "--once" in sys.argv:
        scanner.scan_once()
    elif "--backtest" in sys.argv:
        run_backtest(container.fetcher)
    elif "--dashboard" in sys.argv:
        app = create_default_dashboard_app(container)
        app.run(host="0.0.0.0", port=settings.FLASK_PORT, debug=settings.FLASK_DEBUG)
    else:
        app = create_default_dashboard_app(container)
        t = Thread(
            target=lambda: app.run(host="0.0.0.0", port=settings.FLASK_PORT, debug=False, use_reloader=False),
            daemon=True
        )
        t.start()
        logger.info(f"🌐 Dashboard: http://localhost:{settings.FLASK_PORT}")
        scheduler.run_loop()


if __name__ == "__main__":
    main()
