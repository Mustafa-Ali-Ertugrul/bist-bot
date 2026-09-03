import json
from unittest.mock import MagicMock

from bist_bot.dashboard import create_dashboard_app


def test_livez_endpoint_is_lightweight():
    db = MagicMock()
    circuit = MagicMock()
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
        data = json.loads(res.data)
        assert data["status"] == "alive"
        # livez must NOT ping db
        db.ping.assert_not_called()


def test_ready_and_readyz_check_dependencies():
    db = MagicMock()
    db.ping.return_value = True
    circuit = MagicMock()
    circuit.state = "CLOSED"
    app = create_dashboard_app(
        fetcher=MagicMock(),
        engine=MagicMock(),
        db=db,
        broker=MagicMock(),
        circuit_breaker=circuit,
    )
    app.config["TESTING"] = True
    with app.test_client() as client:
        for path in ("/ready", "/readyz"):
            res = client.get(path)
            assert res.status_code == 200
            data = json.loads(res.data)
            assert data["status"] == "ready"
            assert data["database"] == "ok"

        # When DB down -> 503 not_ready
        db.ping.return_value = False
        res = client.get("/readyz")
        assert res.status_code == 503
        data = json.loads(res.data)
        assert data["status"] == "not_ready"
        assert data["database"] == "error"
