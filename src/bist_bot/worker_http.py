"""Tiny worker HTTP surface: /healthz, /readyz, /metrics (C2/C7).

The scanner worker runs no Flask app; Prometheus still needs to scrape it
and ops needs a readiness signal that reflects *business* health (scan
freshness) without coupling it to liveness — a stale scan degrades
readiness, never restarts the container (see review: liveness ≠ readiness).

Readiness logic:
- outside market hours → ready (nothing to scan).
- inside market hours → degraded(503) when the last successful scan is
  older than WATCHDOG_STALE_MINUTES or no scan has completed yet after a
  grace period following session open.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import render_metrics
from bist_bot.market_calendar import TR, is_bist_open

logger = get_logger(__name__, component="worker_http")

_READY_GRACE_MINUTES = 40


class WorkerHealthServer:
    def __init__(self, scheduler, port: int = 9101, settings=None) -> None:
        self.scheduler = scheduler
        self.port = port
        self.settings = settings
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    # -- readiness -----------------------------------------------------
    def readiness(self) -> tuple[int, dict]:
        from datetime import datetime

        now = datetime.now(TR)
        market_open = is_bist_open(now)
        last = getattr(self.scheduler, "_last_scan_success_at", None)
        stale_minutes = max(5, int(getattr(self.settings, "WATCHDOG_STALE_MINUTES", 30)))
        age_seconds = (now - last).total_seconds() if last is not None else None

        payload = {
            "market_open": market_open,
            "last_scan_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "stale_threshold_minutes": stale_minutes,
            "running": bool(getattr(self.scheduler, "running", False)),
        }
        if not market_open:
            payload["status"] = "ready"
            return 200, payload
        if age_seconds is None:
            # Seans acildi ama henuz tarama yok — acilis sonrasi grace tanimla.
            open_hour = int(getattr(self.settings, "MARKET_OPEN_HOUR", 10))
            open_minutes = now.hour * 60 + now.minute - open_hour * 60
            if 0 <= open_minutes <= _READY_GRACE_MINUTES:
                payload["status"] = "warming_up"
                return 200, payload
            payload["status"] = "degraded_no_scan"
            return 503, payload
        if age_seconds > stale_minutes * 60:
            payload["status"] = "degraded_scan_stale"
            return 503, payload
        payload["status"] = "ready"
        return 200, payload

    # -- HTTP plumbing ---------------------------------------------------
    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/metrics":
                    body = render_metrics().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/healthz":
                    self._json(200, {"status": "alive"})
                    return
                if self.path == "/readyz":
                    code, payload = server.readiness()
                    self._json(code, payload)
                    return
                self._json(404, {"error": "not_found"})

            def _json(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):  # silence default stderr noise
                logger.debug("worker_http_request", path=self.path)

        return Handler

    def start(self) -> None:
        # Container liveness endpoint must listen on all interfaces; the
        # port serves only container-local healthchecks, never the internet.
        bind_host = "0.0.0.0"  # nosec B104
        self._server = ThreadingHTTPServer((bind_host, self.port), self._handler())
        self._thread = Thread(target=self._server.serve_forever, name="worker-http", daemon=True)
        self._thread.start()
        logger.info("worker_http_started", port=self.port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("worker_http_stopped")
