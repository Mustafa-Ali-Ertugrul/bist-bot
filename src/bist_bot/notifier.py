import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests

from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import Signal, SignalType

TR = timezone(timedelta(hours=3))

logger = logging.getLogger(__name__)


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
        self.sender = sender
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "ΓÜá∩╕Å  Telegram ayarlanmam─▒┼ƒ. "
                ".env dosyas─▒na TELEGRAM_BOT_TOKEN ve "
                "TELEGRAM_CHAT_ID ekle."
            )

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            logger.info(f"[TELEGRAM DEVRE DI┼₧I] {text[:80]}...")
            return False

        try:
            sent = self.sender(
                base_url=self.base_url,
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                max_retries=getattr(settings, "NOTIFICATION_MAX_RETRIES", 3),
                retry_delay=getattr(settings, "NOTIFICATION_RETRY_DELAY", 5),
            )
            if sent:
                logger.info("≡ƒô¿ Telegram mesaj─▒ g├╢nderildi")
                return True
            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Γ¥î Telegram hatas─▒: {e}")
            return False

    def send_signal(self, signal: Signal) -> bool:
        name = settings.TICKER_NAMES.get(signal.ticker, signal.ticker)

        emoji_map = {
            SignalType.STRONG_BUY: "≡ƒÜÇ≡ƒÆ░",
            SignalType.BUY: "≡ƒƒó≡ƒôê",
            SignalType.WEAK_BUY: "≡ƒƒí≡ƒôè",
            SignalType.HOLD: "ΓÜ¬ΓÅ╕∩╕Å",
            SignalType.WEAK_SELL: "≡ƒƒá≡ƒôë",
            SignalType.SELL: "≡ƒö┤≡ƒôë",
            SignalType.STRONG_SELL: "≡ƒÜ¿≡ƒö╗",
        }
        emoji = emoji_map.get(signal.signal_type, "≡ƒôè")

        reasons_html = "\n".join([f"  ΓÇó {r}" for r in signal.reasons])

        message = f"""
{emoji} <b>{name}</b> ({signal.ticker.replace(".IS", "")})
ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü

≡ƒôè <b>Sinyal:</b> {signal.signal_type.value}
≡ƒôê <b>Skor:</b> {signal.score:+.0f}/100
≡ƒÄ» <b>G├╝ven:</b> {signal.confidence}

≡ƒÆ░ <b>Fiyat:</b> Γé║{signal.price:.2f}
≡ƒ¢æ <b>Stop-Loss:</b> Γé║{signal.stop_loss:.2f}
≡ƒÄ» <b>Hedef:</b> Γé║{signal.target_price:.2f}

≡ƒôï <b>Nedenler:</b>
{reasons_html}

ΓÅ░ {signal.timestamp.strftime("%d.%m.%Y %H:%M")}
ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü
ΓÜá∩╕Å <i>Bu bir yat─▒r─▒m tavsiyesi de─ƒildir!</i>
"""
        return self.send_message(message.strip())

    def send_scan_summary(self, signals: list[Signal], total_scanned: int) -> bool:
        buys = [s for s in signals if s.score > 0]
        sells = [s for s in signals if s.score < 0]
        holds = [s for s in signals if s.score == 0]

        top_buys = sorted(buys, key=lambda s: s.score, reverse=True)[:3]
        top_sells = sorted(sells, key=lambda s: s.score)[:3]

        top_buys_text = (
            "\n".join(
                [
                    f"  ≡ƒƒó {settings.TICKER_NAMES.get(s.ticker, s.ticker)}: "
                    f"Γé║{s.price:.2f} (Skor: {s.score:+.0f})"
                    for s in top_buys
                ]
            )
            or "  Yok"
        )

        top_sells_text = (
            "\n".join(
                [
                    f"  ≡ƒö┤ {settings.TICKER_NAMES.get(s.ticker, s.ticker)}: "
                    f"Γé║{s.price:.2f} (Skor: {s.score:+.0f})"
                    for s in top_sells
                ]
            )
            or "  Yok"
        )

        now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")

        message = f"""
≡ƒöì <b>BIST TARAMA RAPORU</b>
ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü
ΓÅ░ {now}
≡ƒôè Taranan: {total_scanned} hisse

Γ£à Al─▒m Sinyali: {len(buys)}
Γ¥î Sat─▒┼ƒ Sinyali: {len(sells)}
ΓÅ╕∩╕Å Bekle: {len(holds)}

≡ƒÅå <b>En ─░yi F─▒rsatlar:</b>
{top_buys_text}

ΓÜá∩╕Å <b>Sat─▒┼ƒ Uyar─▒lar─▒:</b>
{top_sells_text}
ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü
"""
        return self.send_message(message.strip())

    def send_signal_change(self, ticker: str, old_signal: Signal, new_signal: Signal) -> bool:
        name = settings.TICKER_NAMES.get(ticker, ticker)

        emoji_map = {
            SignalType.STRONG_BUY: "≡ƒÜÇ≡ƒÆ░",
            SignalType.BUY: "≡ƒƒó≡ƒôê",
            SignalType.WEAK_BUY: "≡ƒƒí≡ƒôè",
            SignalType.HOLD: "ΓÜ¬ΓÅ╕∩╕Å",
            SignalType.WEAK_SELL: "≡ƒƒá≡ƒôë",
            SignalType.SELL: "≡ƒö┤≡ƒôë",
            SignalType.STRONG_SELL: "≡ƒÜ¿≡ƒö╗",
        }

        old_emoji = emoji_map.get(old_signal.signal_type, "≡ƒôè")
        new_emoji = emoji_map.get(new_signal.signal_type, "≡ƒôè")

        direction = "Γ¼å∩╕Å Y├£KSEL─░YOR" if new_signal.score > old_signal.score else "Γ¼ç∩╕Å D├£┼₧├£YOR"

        message = f"""
≡ƒöö <b>S─░NYAL DE─₧─░┼₧─░KL─░─₧─░!</b>
ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü

≡ƒôè <b>{name}</b> ({ticker.replace(".IS", "")})

{old_emoji} {old_signal.signal_type.value}
     Γåô
{new_emoji} <b>{new_signal.signal_type.value}</b>

≡ƒôê <b>Skor:</b> {old_signal.score:+.0f} ΓåÆ <b>{new_signal.score:+.0f}</b>
{direction}

≡ƒÆ░ <b>Yeni Fiyat:</b> Γé║{new_signal.price:.2f}
≡ƒ¢æ <b>Stop-Loss:</b> Γé║{new_signal.stop_loss:.2f}
≡ƒÄ» <b>Hedef:</b> Γé║{new_signal.target_price:.2f}

ΓÅ░ {datetime.now(TR).strftime("%d.%m.%Y %H:%M")}
ΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöüΓöü
ΓÜá∩╕Å <i>Yat─▒r─▒m tavsiyesi de─ƒildir!</i>
"""
        return self.send_message(message.strip())

    def send_startup_message(self):
        msg = (
            "≡ƒñû <b>BIST Bot Ba┼ƒlat─▒ld─▒!</b>\n\n"
            f"≡ƒôè Takip: {len(settings.WATCHLIST)} hisse\n"
            f"ΓÅ▒∩╕Å Tarama: Her {settings.SCAN_INTERVAL_MINUTES} dakika\n"
            f"ΓÅ░ Saat: {datetime.now(TR).strftime('%H:%M')}"
        )
        return self.send_message(msg)


if __name__ == "__main__":
    notifier = TelegramNotifier()
    notifier.send_message("≡ƒº¬ Test mesaj─▒ - BIST Bot ├ºal─▒┼ƒ─▒yor!")
