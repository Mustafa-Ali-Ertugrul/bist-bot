import requests
import logging
from datetime import datetime, timezone, timedelta

TR = timezone(timedelta(hours=3))

import config
from strategy import Signal, SignalType

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(
        self,
        token: str = None,
        chat_id: str = None
    ):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "⚠️  Telegram ayarlanmamış. "
                ".env dosyasına TELEGRAM_BOT_TOKEN ve "
                "TELEGRAM_CHAT_ID ekle."
            )

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            logger.info(f"[TELEGRAM DEVRE DIŞI] {text[:80]}...")
            return False

        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10
            )
            response.raise_for_status()
            logger.info("📨 Telegram mesajı gönderildi")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Telegram hatası: {e}")
            return False

    def send_signal(self, signal: Signal) -> bool:
        name = config.TICKER_NAMES.get(signal.ticker, signal.ticker)

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

        reasons_html = "\n".join(
            [f"  • {r}" for r in signal.reasons]
        )

        message = f"""
{emoji} <b>{name}</b> ({signal.ticker.replace('.IS', '')})
━━━━━━━━━━━━━━━━━━━━

📊 <b>Sinyal:</b> {signal.signal_type.value}
📈 <b>Skor:</b> {signal.score:+.0f}/100
🎯 <b>Güven:</b> {signal.confidence}

💰 <b>Fiyat:</b> ₺{signal.price:.2f}
🛑 <b>Stop-Loss:</b> ₺{signal.stop_loss:.2f}
🎯 <b>Hedef:</b> ₺{signal.target_price:.2f}

📋 <b>Nedenler:</b>
{reasons_html}

⏰ {signal.timestamp.strftime('%d.%m.%Y %H:%M')}
━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Bu bir yatırım tavsiyesi değildir!</i>
"""
        return self.send_message(message.strip())

    def send_scan_summary(
        self,
        signals: list[Signal],
        total_scanned: int
    ) -> bool:
        buys = [s for s in signals if s.score > 0]
        sells = [s for s in signals if s.score < 0]
        holds = [s for s in signals if s.score == 0]

        top_buys = sorted(buys, key=lambda s: s.score)[:3]
        top_sells = sorted(sells, key=lambda s: s.score, reverse=True)[:3]

        top_buys_text = "\n".join([
            f"  🟢 {config.TICKER_NAMES.get(s.ticker, s.ticker)}: "
            f"₺{s.price:.2f} (Skor: {s.score:+.0f})"
            for s in top_buys
        ]) or "  Yok"

        top_sells_text = "\n".join([
            f"  🔴 {config.TICKER_NAMES.get(s.ticker, s.ticker)}: "
            f"₺{s.price:.2f} (Skor: {s.score:+.0f})"
            for s in top_sells
        ]) or "  Yok"

        now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")

        message = f"""
🔍 <b>BIST TARAMA RAPORU</b>
━━━━━━━━━━━━━━━━━━━━
⏰ {now}
📊 Taranan: {total_scanned} hisse

✅ Alım Sinyali: {len(buys)}
❌ Satış Sinyali: {len(sells)}
⏸️ Bekle: {len(holds)}

🏆 <b>En İyi Fırsatlar:</b>
{top_buys_text}

⚠️ <b>Satış Uyarıları:</b>
{top_sells_text}
━━━━━━━━━━━━━━━━━━━━
"""
        return self.send_message(message.strip())

    def send_signal_change(
        self,
        ticker: str,
        old_signal: Signal,
        new_signal: Signal
    ) -> bool:
        name = config.TICKER_NAMES.get(ticker, ticker)

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

📊 <b>{name}</b> ({ticker.replace('.IS', '')})

{old_emoji} {old_signal.signal_type.value}
     ↓
{new_emoji} <b>{new_signal.signal_type.value}</b>

📈 <b>Skor:</b> {old_signal.score:+.0f} → <b>{new_signal.score:+.0f}</b>
{direction}

💰 <b>Yeni Fiyat:</b> ₺{new_signal.price:.2f}
🛑 <b>Stop-Loss:</b> ₺{new_signal.stop_loss:.2f}
🎯 <b>Hedef:</b> ₺{new_signal.target_price:.2f}

⏰ {datetime.now(TR).strftime('%d.%m.%Y %H:%M')}
━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Yatırım tavsiyesi değildir!</i>
"""
        return self.send_message(message.strip())

    def send_startup_message(self):
        msg = (
            "🤖 <b>BIST Bot Başlatıldı!</b>\n\n"
            f"📊 Takip: {len(config.WATCHLIST)} hisse\n"
            f"⏱️ Tarama: Her {config.SCAN_INTERVAL_MINUTES} dakika\n"
            f"⏰ Saat: {datetime.now(TR).strftime('%H:%M')}"
        )
        return self.send_message(msg)


if __name__ == "__main__":
    notifier = TelegramNotifier()
    notifier.send_message("🧪 Test mesajı - BIST Bot çalışıyor!")
