"""Primary runtime entry point for the bot and scheduler process."""

import argparse

from bist_bot.app_logging import configure_logging, get_logger

logger = get_logger(__name__, component="main")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bist-bot",
        description="BIST Bot — çok zaman dilimli teknik analiz ve sinyal üretimi.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modlar (mutual exclusive):\n"
            "  --once          Tekrar tarama çalıştır\n"
            "  --backtest      İzlenenler için backtest çalıştır\n"
            "  --dashboard     Yalnızca Flask dashboard'u başlat\n"
            "  --worker        Yalnızca tarama/izleme döngüsünü çalıştır\n"
            "Varsayılan (mod belirtmezsen): scheduler + dashboard"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--once", action="store_true", help="Tek seferlik tarama")
    group.add_argument("--backtest", action="store_true", help="Backtest modu")
    group.add_argument("--dashboard", action="store_true", help="Sadece dashboard başlat")
    group.add_argument("--worker", action="store_true", help="Sadece worker/scanner döngüsü")
    return parser


def main() -> None:
    """Run the CLI-oriented bot process.

    Modes (mutually exclusive):
      --once       single scan
      --backtest   run watchlist backtests
      --dashboard  run only the Flask dashboard
      --worker     run only the scanner scheduler worker
      default      scheduler + embedded Flask dashboard
    """
    configure_logging()

    from threading import Thread

    from bist_bot.backtest_runner import run_backtest
    from bist_bot.config.settings import settings
    from bist_bot.dashboard import create_default_dashboard_app
    from bist_bot.dependencies import build_scan_service, get_default_container
    from bist_bot.execution.order_tracker import OrderTracker
    from bist_bot.scheduler import MarketScheduler

    args = _build_parser().parse_args()
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

    if args.once:
        scanner.scan_once()
        return

    if args.backtest:
        run_backtest(container.fetcher)
        return

    if args.dashboard:
        app = create_default_dashboard_app(container)
        app.run(
            host="0.0.0.0",
            port=settings.FLASK_PORT,
            debug=False,
            use_reloader=settings.FLASK_DEBUG,
        )
        return

    if args.worker:
        order_tracker.start()
        scheduler.run_loop()
        return

    # default mode: scheduler + dashboard
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
