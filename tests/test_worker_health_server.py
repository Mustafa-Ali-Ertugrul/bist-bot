import time
import urllib.request
from unittest.mock import MagicMock

from bist_bot.worker_http import WorkerHealthServer, _metrics_client_allowed


def test_worker_health_server_start_stop():
    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    server = WorkerHealthServer(scheduler=mock_scheduler, port=9199)
    server.start()
    try:
        time.sleep(0.1)
        res = urllib.request.urlopen("http://127.0.0.1:9199/healthz")
        assert res.status == 200
        assert '{"status": "alive"}' in res.read().decode()
    finally:
        server.stop()

    assert server._server is None
    assert server._thread is None


def test_metrics_client_allowed_private_scrapers():
    assert _metrics_client_allowed("127.0.0.1", False) is True
    assert _metrics_client_allowed("::1", False) is True
    assert _metrics_client_allowed("172.18.0.5", False) is True
    assert _metrics_client_allowed("::ffff:10.0.0.7", False) is True


def test_metrics_client_denied_for_public_clients():
    assert _metrics_client_allowed("8.8.8.8", False) is False
    assert _metrics_client_allowed("2001:4860:4860::8888", False) is False
    assert _metrics_client_allowed("not-an-ip", False) is False
    assert _metrics_client_allowed("", False) is False


def test_metrics_client_allowed_when_public_opt_in():
    assert _metrics_client_allowed("8.8.8.8", True) is True
