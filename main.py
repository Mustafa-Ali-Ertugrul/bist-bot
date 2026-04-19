import io
import logging
import sys
from logging.handlers import RotatingFileHandler

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

handler_file = RotatingFileHandler(
    "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
handler_console = logging.StreamHandler()
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
handler_file.setFormatter(fmt)
handler_console.setFormatter(fmt)
logging.basicConfig(level=logging.INFO, handlers=[handler_file, handler_console])
logger = logging.getLogger(__name__)


def main():
    from data_fetcher import BISTDataFetcher
    from strategy import StrategyEngine
    from notifier import TelegramNotifier
    from database import SignalDatabase
    from scanner import ScanService
    from scheduler import MarketScheduler
    from backtest_runner import run_backtest
    from threading import Thread

    import config

    fetcher = BISTDataFetcher()
    engine = StrategyEngine()
    notifier = TelegramNotifier()
    db = SignalDatabase()
    scanner = ScanService(fetcher, engine, notifier, db)
    scheduler = MarketScheduler(scanner, notifier)

    def shutdown(signum, frame):
        logger.info("🛑 Bot durduruluyor...")
        scheduler.running = False

    import signal as _signal
    _signal.signal(_signal.SIGINT, shutdown)

    if "--once" in sys.argv:
        scanner.scan_once()
    elif "--backtest" in sys.argv:
        run_backtest(fetcher)
    elif "--dashboard" in sys.argv:
        from dashboard import app
        app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
    else:
        from dashboard import app
        t = Thread(
            target=lambda: app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=False, use_reloader=False),
            daemon=True
        )
        t.start()
        logger.info(f"🌐 Dashboard: http://localhost:{config.FLASK_PORT}")
        scheduler.run_loop()


if __name__ == "__main__":
    main()
