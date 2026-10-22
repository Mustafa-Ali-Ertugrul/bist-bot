"""Faz 6: Telegram account linking via single-use deep-link tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.alert_repository import AlertRepository

logger = get_logger(__name__, component="telegram_link")

TOKEN_TTL_MINUTES = 15


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TelegramLinkService:
    def __init__(
        self,
        repository: AlertRepository,
        notifier: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self.repository = repository
        self.notifier = notifier
        self.settings = settings or default_settings

    def bot_username(self) -> str:
        return str(getattr(self.settings, "TELEGRAM_USER_BOT_USERNAME", "") or "").lstrip("@")

    def create_token(self, user_id: int) -> dict[str, str] | None:
        username = self.bot_username()
        if not username:
            return None
        raw = secrets.token_urlsafe(24)
        expires_at = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        self.repository.create_link_token(user_id, hash_token(raw), expires_at)
        return {
            "url": f"https://t.me/{username}?start={raw}",
            "expires_at": expires_at.isoformat(),
        }

    def status(self, user_id: int) -> dict[str, Any]:
        link = self.repository.get_link(user_id)
        return {
            "linked": link is not None,
            "username": link["username"] if link else None,
            "linked_at": link["linked_at"] if link else None,
            "bot_username": self.bot_username() or None,
        }

    def unlink(self, user_id: int) -> None:
        self.repository.delete_link(user_id)

    def handle_message(self, message: dict[str, Any]) -> str | None:
        """Process one Telegram message; returns the reply text (or None)."""
        chat = message.get("chat") or {}
        if str(chat.get("type") or "") != "private":
            return "Bu bot yalnızca özel sohbetlerde kullanılabilir."
        chat_id = str(chat.get("id") or "")
        text = str(message.get("text") or "").strip()
        username = (message.get("from") or {}).get("username")

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            raw = parts[1].strip() if len(parts) > 1 else ""
            if not raw:
                return "Bağlantı için web sitesindeki 'Telegram'ı bağla' bağlantısını kullanın."
            user_id = self.repository.consume_link_token(hash_token(raw))
            if user_id is None:
                return (
                    "Bağlantı geçersiz veya süresi dolmuş. Web sitesinden yeni bağlantı oluşturun."
                )
            self.repository.save_link(user_id, chat_id, username)
            logger.info("telegram_link_created", user_id=user_id)
            return (
                "Bağlantı kuruldu. Akşam özeti ve alarmlarınız bu sohbete gelecek. "
                "Ayrılmak için /stop yazabilirsiniz. Bu mesajlar yatırım tavsiyesi değildir."
            )

        if text.startswith("/stop"):
            self.repository.delete_link_by_chat(chat_id)
            logger.info("telegram_link_removed")
            return "Bağlantı kaldırıldı. Artık bu sohbete özet gönderilmeyecek."

        if text.startswith("/help"):
            return (
                "Komutlar: /start <bağlantı kodu>, /stop, /help. "
                "Alarmlarınızı web sitesindeki Alarmlar sayfasından yönetin."
            )
        return None
