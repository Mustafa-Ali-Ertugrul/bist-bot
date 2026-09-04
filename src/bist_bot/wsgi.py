"""Production WSGI entry point with DB-outage liveness degradation."""

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

from flask import Flask, jsonify

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.dashboard import create_default_dashboard_app
from bist_bot.db import DatabaseInitializationError

logger = get_logger(__name__, component="wsgi")


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
            else getattr(settings, "DEGRADED_MAX_SECONDS", 300)
        )

        @degraded.get("/livez")
        def livez():
            elapsed = time.monotonic() - started_at
            if elapsed > max_sec:
                logger.error(
                    "degraded_mode_lifetime_exceeded_exiting_worker",
                    elapsed_seconds=round(elapsed, 1),
                    max_seconds=max_sec,
                )
                # Exit worker process so Gunicorn master respawns a fresh worker to retry DB init
                sys.exit(1)
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


app = build_wsgi_app()
