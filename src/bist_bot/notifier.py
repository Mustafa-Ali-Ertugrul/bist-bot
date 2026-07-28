import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import Signal, SignalType

TR = timezone(timedelta(hours=3))

logger = get_logger(__name__, component="notifier")


def send_telegram_with_retry(
    base_url: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    max_retries: int = 3,
    retry_delay: int = 5,
) -> bool:
    """Telegram mesaji gonderir, gecici hatalarda retry yapar."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{base_url}/sendMessage",
                json=payload,
                timeout=10,
            )
            if response.status_code in {403, 404}:
                response.raise_for_status()
            response.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            status_code = getattr(e.response, "status_code", None)
            if status_code in {403, 404}:
                raise
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise
        except requests.exceptions.RequestException:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise

    return False


class TelegramNotifier:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        sender: Callable[..., bool] = send_telegram_with_retry,
    ):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.group_chat_id = getattr(settings, "TELEGRAM_GROUP_CHAT_ID", "") or None
        self.sender = sender
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "telegram_not_configured",
                detail="Telegram ayarlanmamış. .env dosyasına TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ekle.",
            )

    def _send(self, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            logger.info("telegram_disabled", preview=text[:80])
            return False

        try:
            sent = self.sender(
                base_url=self.base_url,
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                max_retries=getattr(settings, "NOTIFICATION_MAX_RETRIES", 3),
                retry_delay=getattr(settings, "NOTIFICATION_RETRY_DELAY", 5),
            )
            if sent:
                logger.info("telegram_message_sent", preview=text[:80])
                return True
            return False

        except requests.exceptions.RequestException as e:
            logger.error("telegram_error", error=str(e))
            return False

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        return self._send(self.chat_id, text, parse_mode)

    def send_to_group(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the Telegram group chat."""
        chat_id = self.group_chat_id or self.chat_id
        return self._send(chat_id, text, parse_mode)

    # ------------------------------------------------------------------
    # Detail message: split into actionable vs radar labels with diagnosis
    # ------------------------------------------------------------------
    def _build_diagnosis_block(self, signal: Signal) -> str:
        """Return the  🔍 Teşhis block for a signal."""
        # Confidence level derived from signal.confidence (agreement-based, single source).
        conf_key = signal.confidence
        if conf_key == "confidence.high":
            level = "high"
        elif conf_key == "confidence.medium":
            level = "medium"
        else:
            level = "low"
        agree_int = {"confidence.high": 3, "confidence.medium": 2, "confidence.low": 1}.get(
            conf_key, 0
        )
        agree_str = f"{agree_int}/4"
        lines = [f"  Bileşen uyumu: {agree_str} → {level}"]

        # Gates reasons block
        gate_keywords = [
            "Karşıt-trend bastırma",
            "Aşırı uzama chase koruması",
            "MTF çelişki",
            "nötr",
            "Hacim divergence",
            "bastırıldı",
        ]
        gate_reasons = [
            r for r in signal.reasons if any(kw in r for kw in gate_keywords)
        ]
        if gate_reasons:
            lines.append("  🛡️ Uygulanan korumalar:")
            for gr in gate_reasons:
                lines.append(f"    • {gr}")
        else:
            lines.append("  🛡️ Koruma tetiklenmedi")

        # Threshold info — engine owns the threshold, signal carries it
        lines.append(
            f"  Skor {signal.score:+.0f} / actionable eşiği {signal.buy_threshold}"
            f" → {'actionable' if signal.is_actionable else 'radar'}"
        )

        return "\n".join(lines)

    def _signal_label(self, signal: Signal) -> str:
        """Return the one-line label for a signal detail message."""
        if signal.is_actionable:
            return "<b>AL SİNYALİ</b> (actionable — paper'da emir simüle edilir)"
        if signal.score > 0:
            return "<b>RADAR / İZLE</b> (henüz actionable DEĞİL — emir YOK, sadece izleme)"
        return f"{signal.signal_type.value}"

    def send_signal(self, signal: Signal) -> bool:
        name = settings.TICKER_NAMES.get(signal.ticker, signal.ticker)

        label_line = self._signal_label(signal)

        emoji_map = {
            SignalType.STRONG_BUY: "🚀💰",
            SignalType.BUY: "🟢📈",
            SignalType.WEAK_BUY: "🟡📊",
            SignalType.HOLD: "⚪⏸️",
            SignalType.WEAK_SELL: "🟠📉",
            SignalType.SELL: "🔴📉",
            SignalType.STRONG_SELL: "🚨🔻",
        }
        emoji = emoji_map.get(signal.signal_type, "📊")

        reasons_html = "\n".join([f"  • {r}" for r in signal.reasons])

        diagnosis = self._build_diagnosis_block(signal)

        message = f"""
{emoji} <b>{name}</b> ({signal.ticker.replace(".IS", "")})
━━━━━━━━━━━━━━━━━━━━

{label_line}
📈 <b>Skor:</b> {signal.score:+.0f}/100
🎯 <b>Güven:</b> {signal.confidence}

💰 <b>Fiyat:</b> ₺{signal.price:.2f}
🛑 <b>Stop-Loss:</b> ₺{signal.stop_loss:.2f}
🎯 <b>Hedef:</b> ₺{signal.target_price:.2f}

📋 <b>Nedenler:</b>
{reasons_html}

🔍 <b>Teşhis:</b>
{diagnosis}

⏰ {signal.timestamp.strftime("%d.%m.%Y %H:%M")}
━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Bu bir yatırım tavniyesi değildir!</i>
"""
        return self.send_message(message.strip())

    def send_scan_summary(self, signals: list[Signal], total_scanned: int) -> bool:
        buys = [s for s in signals if s.is_actionable and s.score > 0]
        radars = [s for s in signals if not s.is_actionable and s.score > 0]
        sells = [s for s in signals if s.score < 0]
        holds = [s for s in signals if s.score == 0]

        top_opportunities = sorted(
            [*buys, *radars], key=lambda s: s.score, reverse=True
        )[:3]
        top_sells = sorted(sells, key=lambda s: s.score)[:3]

        top_opportunities_text = (
            "\n".join(
                [
                    f"  {'🟢' if s.is_actionable else '🟡'} "
                    f"{settings.TICKER_NAMES.get(s.ticker, s.ticker)}: "
                    f"₺{s.price:.2f} (Skor: {s.score:+.0f}) — "
                    f"{'AL' if s.is_actionable else 'RADAR'}"
                    for s in top_opportunities
                ]
            )
            or "  Yok"
        )

        top_sells_text = (
            "\n".join(
                [
                    f"  🔴 {settings.TICKER_NAMES.get(s.ticker, s.ticker)}: "
                    f"₺{s.price:.2f} (Skor: {s.score:+.0f})"
                    for s in top_sells
                ]
            )
            or "  Yok"
        )

        now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")

        message = f"""
🔍 <b>BIST TARAMA RAPORU</b>
━━━━━━━━━━━━━━━━━━━━
⏰ {now}
📊 Taranan: {total_scanned} hisse

✅ Alım Sinyali: {len(buys)}
🟡 Radar / İzle: {len(radars)}
❌ Satış Sinyali: {len(sells)}
⏸️ Bekle: {len(holds)}

🏆 <b>En İyi Fırsatlar:</b>
{top_opportunities_text}

⚠️ <b>Satış Uyarıları:</b>
{top_sells_text}
━━━━━━━━━━━━━━━━━━━━
"""
        return self.send_message(message.strip())

    def send_signal_change(self, ticker: str, old_signal: Signal, new_signal: Signal) -> bool:
        name = settings.TICKER_NAMES.get(ticker, ticker)

        emoji_map = {
            SignalType.STRONG_BUY: "🚀💰",
            SignalType.BUY: "🟢📈",
            SignalType.WEAK_BUY: "🟡📊",
            SignalType.HOLD: "⚪⏸️",
            SignalType.WEAK_SELL: "🟠📉",
            SignalType.SELL: "🔴📉",
            SignalType.STRONG_SELL: "🚨🔻",
        }

        old_emoji = emoji_map.get(old_signal.signal_type, "📊")
        new_emoji = emoji_map.get(new_signal.signal_type, "📊")

        direction = "⬆️ YÜKSELİYOR" if new_signal.score > old_signal.score else "⬇️ DÜŞÜYOR"

        message = f"""
🔔 <b>SİNYAL DEĞİŞİKLİĞİ!</b>
━━━━━━━━━━━━━━━━━━━━

📊 <b>{name}</b> ({ticker.replace(".IS", "")})

{old_emoji} {old_signal.signal_type.value}
     ↓
{new_emoji} <b>{new_signal.signal_type.value}</b>

📈 <b>Skor:</b> {old_signal.score:+.0f} → <b>{new_signal.score:+.0f}</b>
{direction}

💰 <b>Yeni Fiyat:</b> ₺{new_signal.price:.2f}
🛑 <b>Stop-Loss:</b> ₺{new_signal.stop_loss:.2f}
🎯 <b>Hedef:</b> ₺{new_signal.target_price:.2f}

⏰ {datetime.now(TR).strftime("%d.%m.%Y %H:%M")}
━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Yatırım tavniyesi değildir!</i>
"""
        return self.send_message(message.strip())

    def send_startup_message(self):
        msg = (
            "🤖 <b>BIST Bot Başlatıldı!</b>\n\n"
            f"📊 Takip: {len(settings.WATCHLIST)} hisse\n"
            f"⏱️ Tarama: Her {settings.SCAN_INTERVAL_MINUTES} dakika\n"
            f"⏰ Saat: {datetime.now(TR).strftime('%H:%M')}"
        )
        return self.send_message(msg)


if __name__ == "__main__":
    notifier = TelegramNotifier()
    notifier.send_message("🧪 Test mesajı - BIST Bot çalışıyor!")
