from unittest.mock import MagicMock

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app


def test_livez_endpoint_is_lightweight():
    db = MagicMock()
    circuit = MagicMock()
    with settings.override(JWT_SECRET_KEY="test-secret-key-12345678901234567890"):
        app = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=db,
            broker=MagicMock(),
            circuit_breaker=circuit,
        )
        app.config["TESTING"] = True
        with app.test_client() as client:
            res = client.get("/livez")
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "alive"
            # livez must NOT ping db
            db.ping.assert_not_called()


def test_readyz_checks_dependencies():
    db = MagicMock()
    db.ping.return_value = True
    circuit = MagicMock()
    circuit.state = "CLOSED"
    with settings.override(JWT_SECRET_KEY="test-secret-key-12345678901234567890"):
        app = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=db,
            broker=MagicMock(),
            circuit_breaker=circuit,
        )
        app.config["TESTING"] = True
        with app.test_client() as client:
            res = client.get("/readyz")
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "ready"
            assert data["database"] == "ok"

            # When DB down -> 503 not_ready on readyz
            db.ping.return_value = False
            res = client.get("/readyz")
            assert res.status_code == 503
            data = res.get_json()
            assert data["status"] == "not_ready"
            assert data["database"] == "error"
