from __future__ import annotations

from bist_bot.db import DatabaseInitializationError
from bist_bot.wsgi import build_wsgi_app


def test_database_outage_keeps_liveness_but_fails_readiness() -> None:
    def unavailable():
        raise DatabaseInitializationError("database unavailable")

    app = build_wsgi_app(unavailable)
    app.config["TESTING"] = True
    client = app.test_client()

    live = client.get("/livez")
    ready = client.get("/readyz")
    health = client.get("/health")

    assert live.status_code == 200
    assert live.get_json()["degraded"] is True
    assert ready.status_code == 503
    assert health.status_code == 503
