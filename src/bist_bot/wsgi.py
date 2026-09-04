"""Production WSGI entry point with DB-outage liveness degradation."""

from collections.abc import Callable
from datetime import UTC, datetime

from flask import Flask, jsonify

from bist_bot.app_logging import get_logger
from bist_bot.dashboard import create_default_dashboard_app
from bist_bot.db import DatabaseInitializationError

logger = get_logger(__name__, component="wsgi")


def build_wsgi_app(factory: Callable[[], Flask] = create_default_dashboard_app) -> Flask:
    try:
        return factory()
    except DatabaseInitializationError:
        logger.exception("database_unavailable_starting_degraded_liveness")
        degraded = Flask(__name__)

        @degraded.get("/livez")
        def livez():
            return jsonify(
                {
                    "status": "alive",
                    "degraded": True,
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
