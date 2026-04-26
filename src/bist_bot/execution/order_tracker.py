"""Background polling for broker order lifecycle synchronization."""

from __future__ import annotations

import threading

from bist_bot.app_logging import get_logger
from bist_bot.contracts import ExecutionProviderProtocol, SignalRepositoryProtocol

logger = get_logger(__name__, component="order_tracker")


class OrderTracker:
    def __init__(
        self,
        broker: ExecutionProviderProtocol,
        db: SignalRepositoryProtocol,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self.broker = broker
        self.db = db
        self.poll_interval_seconds = poll_interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval_seconds * 2)

    def poll_once(self) -> None:
        for order in self.db.get_pending_orders():
            broker_order_id = order.get("broker_order_id")
            if not broker_order_id:
                continue
            status = self.broker.get_order_status(str(broker_order_id))
            self.db.update_order(
                int(order["id"]),
                state=status.state.value,
                broker_order_id=status.broker_order_id,
                filled_qty=status.filled_quantity,
                avg_fill_price=status.average_fill_price,
            )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.warning("order_tracker_poll_failed", error=str(exc))
            self._stop_event.wait(self.poll_interval_seconds)
