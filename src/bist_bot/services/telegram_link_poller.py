"""Faz 6: long-polling reader for /start and /stop from the customer bot.

Telegram allows one consumer per bot. This poller is started in the worker and
persists its update offset in app_settings, so a restart does not replay old
messages. It never runs in tests unless explicitly constructed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import requests

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.alert_repository import AlertRepository
from bist_bot.db.repositories.config_repository import ConfigRepository
from bist_bot.services.telegram_link_service import TelegramLinkService

logger = get_logger(__name__, component="telegram_poll")

OFFSET_KEY = "telegram_update_offset"


class TelegramLinkPoller:
    def __init__(
        self,
        repository: AlertRepository,
        link_service: TelegramLinkService,
        token: str,
        *,
        config_repository: ConfigRepository | None = None,
        transport: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.link_service = link_service
        self.token = token
        self.config = config_repository or ConfigRepository()
        self.settings = settings or default_settings
        self.transport = transport or self._http_transport

    def bot_token(self) -> str:
        return self.token or str(getattr(self.settings, "TELEGRAM_USER_BOT_TOKEN", "") or "")

    def _http_transport(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        token = self.bot_token()
        if not token:
            return {"ok": False}
        url = f"https://api.telegram.org/bot{token}/{method}"
        try:
            response = requests.get(url, params=params, timeout=35)
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("telegram_poll_transport_failed", error_type=type(exc).__name__)
            return {"ok": False}

    def _offset(self) -> int:
        value = self.config.get_config(OFFSET_KEY, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def poll_once(self) -> int:
        """Fetch and process pending updates; returns how many were handled."""
        if not self.bot_token():
            return 0
        payload = self.transport("getUpdates", {"offset": self._offset() + 1, "timeout": 0})
        if not payload.get("ok"):
            return 0
        handled = 0
        for update in payload.get("result") or []:
            update_id = int(update.get("update_id") or 0)
            if update_id:
                self.config.save_config(OFFSET_KEY, update_id)
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue
            reply = self.link_service.handle_message(message)
            if reply:
                chat_id = str((message.get("chat") or {}).get("id") or "")
                if chat_id and self.link_service.notifier is not None:
                    self.link_service.notifier.send_to_chat(chat_id, reply)
            handled += 1
        return handled

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop = stop_event or threading.Event()
        logger.info("telegram_poller_started")
        while not stop.is_set():
            try:
                handled = self.poll_once()
            except Exception as exc:  # never kill the worker thread
                logger.error("telegram_poll_failed", error_type=type(exc).__name__)
                handled = 0
            if not handled:
                time.sleep(3)
        logger.info("telegram_poller_stopped")

    def start_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="telegram-link-poller", daemon=True)
        thread.start()
        return thread
