"""Haber botu Telegram bildirim modülü.

Katman/skor bilgilerini alıp okuyucu formatında Telegram mesajı gönderir
ve ``newsbot_notifications`` tablosuna kayıt eder.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from bist_bot.app_logging import get_logger
from bist_bot.notifier import send_telegram_with_retry

logger = get_logger("newsbot.notifier")

_LAYER_EMOJI: dict[str, str] = {
    "stock": "📈",
    "macro": "🏦",
    "global": "🌍",
}

_DIRECTION_LABEL: dict[str, str] = {
    "positive": "Olumlu",
    "negative": "Olumsuz",
    "neutral": "Nötr",
}

_IMPACT_LABEL: dict[str, str] = {
    "high": "Yüksek",
    "medium": "Orta",
    "low": "Düşük",
}

_MAX_MESSAGE_LEN = 4096  # Telegram API limit


def build_message(
    *,
    title: str,
    layer: str,
    score: int,
    direction: str,
    source_name: str,
    symbol: str | None = None,
    matched_keywords: dict[str, list[str]] | None = None,
) -> str:
    """Tek bir haber için Telegram mesajı metnini oluşturur."""
    matched = matched_keywords or {}
    pos_lines = [f"    • {kw}" for kw in matched.get("positive", [])]
    neg_lines = [f"    • {kw}" for kw in matched.get("negative", [])]
    keywords_block = "\n".join((*pos_lines, *neg_lines)) if (pos_lines or neg_lines) else "    (eşleşen keyword yok)"

    layer_emoji = _LAYER_EMOJI.get(layer, "📰")
    direction_label = _DIRECTION_LABEL.get(direction, direction)

    parts = [
        f"{layer_emoji} <b>[{layer.upper()}]</b> {symbol or 'GENEL'}",
        "",
        f"📰 <b>{title}</b>",
        "",
        f"📊 <b>Skor:</b> {score}/10  •  <b>{direction_label}</b>",
        f"🎯 <b>Etki:</b> {_IMPACT_LABEL.get(_impact_level(score), 'düşük')}",
        "",
        f"📡 <b>Kaynak:</b> {source_name}",
        "",
        f"<b>Eşleşen keyword'ler:</b>\n{keywords_block}",
        "",
        "⚠️ <i>Bu bir yatırım tavsiyesi değildir!</i>",
    ]
    return "\n".join(parts)


def _impact_level(score: int) -> str:
    if score <= 3 or score >= 8:
        return "high"
    if score == 4 or score == 7:
        return "medium"
    return "low"


class NewsbotNotifier:
    """Haber katman/skor sonuçlarını Telegram'a gönderir ve DB'ye kaydeder."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        min_score: int = 7,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.min_score = min_score
        self.enabled = bool(token and chat_id and min_score > 0)
        self.base_url = f"https://api.telegram.org/bot{token}"

    def notify(
        self,
        session: Session,
        *,
        article_id: int,
        title: str,
        layer: str,
        score: int,
        direction: str,
        source_name: str,
        symbol: str | None = None,
        matched_keywords: dict[str, list[str]] | None = None,
    ) -> bool:
        """Bildirimi gönderir; gerekli görüldüğünde DB'ye kaydeder."""
        if not self.enabled:
            logger.debug("newsbot_telegram_disabled")
            return False

        if score < self.min_score:
            logger.debug(
                "newsbot_score_below_threshold",
                article_id=article_id,
                score=score,
                threshold=self.min_score,
            )
            return False

        message = build_message(
            title=title,
            layer=layer,
            score=score,
            direction=direction,
            source_name=source_name,
            symbol=symbol,
            matched_keywords=matched_keywords,
        )
        if len(message) > _MAX_MESSAGE_LEN:
            message = message[: _MAX_MESSAGE_LEN - 3] + "..."

        payload_json = json.dumps(
            {
                "article_id": article_id,
                "layer": layer,
                "score": score,
                "direction": direction,
                "source_name": source_name,
                "symbol": symbol,
                "matched_keywords": matched_keywords or {},
            },
            ensure_ascii=False,
        )

        sent = False
        telegram_message_id: int | None = None
        try:
            resp = send_telegram_with_retry(
                base_url=self.base_url,
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
                max_retries=3,
                retry_delay=5,
            )
            if resp:
                sent = True
                logger.info("newsbot_notification_sent", article_id=article_id, score=score)
        except Exception as exc:
            logger.error("newsbot_telegram_error", error=str(exc))

        ts = datetime.now(UTC).isoformat()
        status = "sent" if sent else "failed"

        session.execute(
            text(
                """
                INSERT INTO newsbot_notifications
                    (article_id, layer, symbol_id, telegram_chat_id, telegram_message_id,
                     payload_json, sent_at, status)
                VALUES (:article_id, :layer, NULL, :chat_id, :msg_id,
                        :payload_json, :sent_at, :status)
                """
            ),
            {
                "article_id": article_id,
                "layer": layer,
                "chat_id": self.chat_id,
                "msg_id": telegram_message_id,
                "payload_json": payload_json,
                "sent_at": ts,
                "status": status,
            },
        )
        return sent
