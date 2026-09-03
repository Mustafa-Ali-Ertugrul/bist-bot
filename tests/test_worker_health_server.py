import time
import urllib.request
from unittest.mock import MagicMock

from bist_bot.worker_http import WorkerHealthServer


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
