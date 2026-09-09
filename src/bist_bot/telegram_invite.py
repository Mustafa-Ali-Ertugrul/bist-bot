"""Pro+ single-use Telegram channel invite links.

Faz 1 scope: link creation is automatic on Pro+ approval
(``member_limit=1``, 48h expiry); removing already-joined members whose
subscription later lapses stays manual (Telegram only exposes membership
via join-request approval flow — Faz 2). Revocation kills the *link*,
never an existing membership.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings

logger = get_logger(__name__, component="telegram_invite")

_API_TIMEOUT_SECONDS = 10


def _api_url(method: str) -> str | None:
    token = str(getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "")
    if not token:
        return None
    return f"https://api.telegram.org/bot{token}/{method}"


def create_pro_invite_link() -> str | None:
    """Mint a single-use Pro+ channel invite link (or None on any failure)."""
    url = _api_url("createChatInviteLink")
    channel_id = str(getattr(settings, "TELEGRAM_PRO_CHANNEL_ID", "") or "")
    if url is None or not channel_id:
        logger.warning("pro_invite_not_configured")
        return None
    hours = max(1, int(getattr(settings, "TELEGRAM_INVITE_HOURS", 48) or 48))
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": channel_id,
                "member_limit": 1,
                "expire_date": int(time.time()) + hours * 3600,
            },
            timeout=_API_TIMEOUT_SECONDS,
        )
        data: Any = resp.json()
    except Exception as exc:
        logger.warning("pro_invite_network_error", error=str(exc)[:160])
        return None
    if resp.status_code == 200 and isinstance(data, dict) and data.get("ok"):
        link = str(((data.get("result") or {}).get("invite_link")) or "")
        if link:
            logger.info("pro_invite_created")
            return link
    logger.warning(
        "pro_invite_failed",
        status=resp.status_code,
        description=str(data.get("description") if isinstance(data, dict) else data)[:160],
    )
    return None


def revoke_invite_link(invite_link: str) -> bool:
    """Revoke a previously minted invite link (best-effort)."""
    url = _api_url("revokeChatInviteLink")
    channel_id = str(getattr(settings, "TELEGRAM_PRO_CHANNEL_ID", "") or "")
    if url is None or not channel_id or not invite_link:
        return False
    try:
        resp = requests.post(
            url,
            json={"chat_id": channel_id, "invite_link": invite_link},
            timeout=_API_TIMEOUT_SECONDS,
        )
        data = resp.json()
        return bool(resp.status_code == 200 and isinstance(data, dict) and data.get("ok"))
    except Exception as exc:
        logger.warning("pro_invite_revoke_error", error=str(exc)[:160])
        return False
