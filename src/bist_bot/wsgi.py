"""Production WSGI entry point with DB-outage liveness degradation."""

import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from flask import Flask, jsonify

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.dashboard import create_default_dashboard_app
from bist_bot.db import DatabaseInitializationError

logger = get_logger(__name__, component="wsgi")


def _schedule_degraded_exit(max_seconds: int) -> None:
    """Kill this worker process after the degraded lifetime expires.

    Runs on a daemon timer thread so expiry does not depend on probe traffic.
    SIGTERM lets a Gunicorn worker exit gracefully; the master respawns a fresh
    worker that retries DB initialization. A fallback os._exit guards runtimes
    that ignore SIGTERM.
    """

    def _expire() -> None:
        logger.error(
            "degraded_mode_lifetime_exceeded_exiting_worker",
            max_seconds=max_seconds,
        )
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            logger.exception("degraded_sigterm_failed")
            os._exit(1)

    timer = threading.Timer(max_seconds, _expire)
    timer.daemon = True
    timer.start()


def build_wsgi_app(
    factory: Callable[[], Flask] = create_default_dashboard_app,
    *,
    degraded_max_seconds: int | None = None,
) -> Flask:
    try:
        return factory()
    except DatabaseInitializationError:
        logger.exception("database_unavailable_starting_degraded_liveness")
        degraded = Flask(__name__)
        started_at = time.monotonic()
        max_sec = (
            degraded_max_seconds
            if degraded_max_seconds is not None
            else int(getattr(settings, "DEGRADED_MAX_SECONDS", 300))
        )
        _schedule_degraded_exit(max_sec)

        @degraded.get("/livez")
        def livez():
            elapsed = time.monotonic() - started_at
            if elapsed > max_sec:
                return jsonify({"status": "dead", "reason": "degraded_lifetime_exceeded"}), 503
            return jsonify(
                {
                    "status": "alive",
                    "degraded": True,
                    "elapsed_seconds": round(elapsed, 1),
                    "max_seconds": max_sec,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        @degraded.get("/readyz")
        @degraded.get("/ready")
        @degraded.get("/health")
        def not_ready():
            return jsonify({"status": "not_ready", "reason": "database_unavailable"}), 503

        return degraded


# When imported as a module (e.g. by tests), app is lazily instantiated or instantiated on demand.
# In a WSGI server (Gunicorn), gunicorn imports `bist_bot.wsgi:app`.
class _LazyApp:
    def __init__(self):
        self._app = None

    def __call__(self, environ, start_response):
        if self._app is None:
            self._app = build_wsgi_app()
        return self._app(environ, start_response)

    def __getattr__(self, name):
        if self._app is None:
            self._app = build_wsgi_app()
        return getattr(self._app, name)


app = _LazyApp()
