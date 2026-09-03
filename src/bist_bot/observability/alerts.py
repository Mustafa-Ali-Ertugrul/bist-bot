"""Critical-event alerting via webhook (Slack/Telegram-compatible).

Configure with ``ALERT_WEBHOOK_URL``. When unset, alerts are logged only.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from bist_bot.app_logging import get_logger

logger = get_logger(__name__, component="alerts")


class AlertLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Alert:
    title: str
    message: str
    level: AlertLevel = AlertLevel.WARNING
    ticker: str | None = None
    order_id: str | None = None
    error: str | None = None
    extra: dict[str, Any] | None = None


class AlertManager:
    """Send structured alerts to a webhook URL."""

    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        timeout_seconds: float = 5.0,
        enabled: bool | None = None,
        transport: Any | None = None,
    ) -> None:
        self.webhook_url = (webhook_url or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        self.enabled = bool(self.webhook_url) if enabled is None else bool(enabled)
        self._transport = transport or self._default_transport
        self._lock = threading.Lock()
        self.last_payload: dict[str, Any] | None = None
        self.sent_count = 0
        self.fail_count = 0

    def send(self, alert: Alert) -> bool:
        payload = self._build_payload(alert)
        logger.warning(
            "alert_raised",
            alert_level=str(alert.level),
            title=alert.title,
            ticker=alert.ticker or "",
            order_id=alert.order_id or "",
            error=alert.error or "",
            detail=alert.message,
        )
        if not self.enabled or not self.webhook_url:
            logger.info("alert_skipped_no_webhook", title=alert.title)
            return False
        try:
            ok = bool(self._transport(self.webhook_url, payload, self.timeout_seconds))
            with self._lock:
                self.last_payload = payload
                if ok:
                    self.sent_count += 1
                else:
                    self.fail_count += 1
            if ok:
                logger.info("alert_sent", title=alert.title, alert_level=str(alert.level))
            else:
                logger.error(
                    "alert_send_failed", title=alert.title, error="transport_returned_false"
                )
            return ok
        except Exception as exc:
            with self._lock:
                self.fail_count += 1
            logger.error(
                "alert_send_failed",
                title=alert.title,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    def send_critical(
        self,
        title: str,
        message: str,
        *,
        ticker: str | None = None,
        order_id: str | None = None,
        error: str | None = None,
        **extra: Any,
    ) -> bool:
        return self.send(
            Alert(
                title=title,
                message=message,
                level=AlertLevel.CRITICAL,
                ticker=ticker,
                order_id=order_id,
                error=error,
                extra=extra or None,
            )
        )

    def _build_payload(self, alert: Alert) -> dict[str, Any]:
        text = f"[{alert.level.value.upper()}] {alert.title}: {alert.message}"
        fields: dict[str, Any] = {
            "title": alert.title,
            "message": alert.message,
            "level": str(alert.level),
            "ticker": alert.ticker or "",
            "order_id": alert.order_id or "",
            "error": alert.error or "",
        }
        if alert.extra:
            fields.update(alert.extra)
        # Slack-compatible envelope + generic fields for other webhooks.
        return {
            "text": text,
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ],
            **fields,
        }

    @staticmethod
    def _default_transport(url: str, payload: dict[str, Any], timeout: float) -> bool:
        # Only http(s) webhook URLs are allowed (operator-configured
        # ALERT_WEBHOOK_URL); file:/custom schemes are rejected.
        if not url.startswith(("https://", "http://")):
            return False
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "bist-bot-alerts/1.0"},
            method="POST",
        )
        try:
            # nosec B310: url scheme is validated to http(s) above; the target
            # is the operator-configured ALERT_WEBHOOK_URL (Slack/generic).
            with urlrequest.urlopen(req, timeout=timeout) as response:  # nosec B310
                return 200 <= int(getattr(response, "status", 200)) < 300
        except urlerror.HTTPError as exc:
            return 200 <= int(exc.code) < 300
        except urlerror.URLError:
            return False


_MANAGER: AlertManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_alert_manager() -> AlertManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            from bist_bot.config.settings import settings

            _MANAGER = AlertManager(
                webhook_url=getattr(settings, "ALERT_WEBHOOK_URL", "") or "",
                timeout_seconds=float(getattr(settings, "ALERT_TIMEOUT_SECONDS", 5.0) or 5.0),
            )
        return _MANAGER


def reset_alert_manager(manager: AlertManager | None = None) -> None:
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = manager


def send_alert(
    title: str,
    message: str,
    *,
    level: AlertLevel | str = AlertLevel.WARNING,
    ticker: str | None = None,
    order_id: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> bool:
    alert_level = level if isinstance(level, AlertLevel) else AlertLevel(str(level).lower())
    return get_alert_manager().send(
        Alert(
            title=title,
            message=message,
            level=alert_level,
            ticker=ticker,
            order_id=order_id,
            error=error,
            extra=extra or None,
        )
    )


__all__ = [
    "Alert",
    "AlertLevel",
    "AlertManager",
    "get_alert_manager",
    "reset_alert_manager",
    "send_alert",
]
