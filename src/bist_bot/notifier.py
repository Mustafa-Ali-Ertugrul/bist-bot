import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import (
    Signal,
    SignalCategory,
    SignalType,
    categorize_signal,
)

TR = timezone(timedelta(hours=3))

logger = get_logger(__name__, component="notifier")

# Single codebase-wide default for the Telegram outbound rate budget.
_DEFAULT_RATE_LIMIT_PER_MINUTE = 18
# Hard cap applied to any Retry-After the API sends, so a misbehaving
# backend can never block the scan worker for minutes.
_MAX_RETRY_AFTER_SECONDS = 30.0
# Cap for the bounded exponential fallback backoff.
_MAX_BACKOFF_SECONDS = 30.0


class SlidingWindowRateLimiter:
    """Sliding-window limiter bounding outbound Telegram messages per minute."""

    def __init__(
        self,
        limit_per_minute: int,
        clock: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._limit = max(1, int(limit_per_minute))
        self._window_seconds = 60.0
        self._timestamps: deque[float] = deque()
        self._clock = clock or time.monotonic
        self._sleep = sleep_fn or time.sleep

    @property
    def limit_per_minute(self) -> int:
        return self._limit

    def configure(self, limit_per_minute: int) -> None:
        """Update the send budget without dropping the window history."""
        self._limit = max(1, int(limit_per_minute))

    def _drop_expired(self, now: float) -> None:
        cutoff = self._window_seconds
        while self._timestamps and now - self._timestamps[0] >= cutoff:
            self._timestamps.popleft()

    def wait_time(self) -> float:
        """Seconds until the next send is allowed (0 when a slot is free)."""
        now = self._clock()
        self._drop_expired(now)
        if len(self._timestamps) < self._limit:
            return 0.0
        return max(0.0, self._window_seconds - (now - self._timestamps[0]))

    def acquire(self) -> float:
        """Block until a send slot is available; return seconds waited."""
        waited = 0.0
        while True:
            now = self._clock()
            self._drop_expired(now)
            if len(self._timestamps) < self._limit:
                self._timestamps.append(now)
                return waited
            delay = max(0.0, self._window_seconds - (now - self._timestamps[0]))
            self._sleep(delay)
            waited += delay


_RATE_LIMITER = SlidingWindowRateLimiter(
    int(getattr(settings, "TELEGRAM_RATE_LIMIT_PER_MINUTE", _DEFAULT_RATE_LIMIT_PER_MINUTE))
)


def get_telegram_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the process-wide limiter shared by all Telegram sends."""
    return _RATE_LIMITER


def configure_telegram_rate_limit(limit_per_minute: int | None) -> None:
    """Update the process-wide send budget (e.g. after settings reload)."""
    if limit_per_minute is None:
        return
    _RATE_LIMITER.configure(limit_per_minute)


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Parse a Telegram Retry-After header, capping it to a sane maximum."""
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(value, _MAX_RETRY_AFTER_SECONDS))


def _backoff_delay(attempt: int, base_delay: float) -> float:
    """Bounded exponential fallback: base * 2^n capped at 30s."""
    return min(_MAX_BACKOFF_SECONDS, float(base_delay) * (2 ** max(0, attempt)))


def send_telegram_with_retry(
    base_url: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    max_retries: int = 3,
    retry_delay: int = 5,
    rate_limit_per_minute: int | None = None,
) -> bool:
    """Telegram mesaji gonderir, gecici hatalarda retry yapar.

    Retry strategy:
    - 429: respect the API ``Retry-After`` (capped) and keep retrying until the
      budget is exhausted; then the message is dead-lettered (logged, not raised).
    - 403/404: permanent channel failures, dead-lettered without retry and raised.
    - other transient errors: bounded exponential fallback, raise on the final attempt.
    """
    limiter = get_telegram_rate_limiter()
    if rate_limit_per_minute is not None:
        limiter.configure(rate_limit_per_minute)

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    total_attempts = max(1, int(max_retries))
    transient_failures = 0
    rate_limit_hit = False

    for attempt in range(total_attempts):
        limiter.acquire()
        try:
            response = requests.post(
                f"{base_url}/sendMessage",
                json=payload,
                timeout=10,
            )
            if response.status_code == 200:
                return True
            if response.status_code in {403, 404}:
                logger.error(
                    "telegram_dead_letter",
                    reason="permanent_error",
                    status_code=response.status_code,
                    preview=text[:80],
                )
                response.raise_for_status()
            if response.status_code == 429:
                rate_limit_hit = True
                delay = _retry_after_seconds(response)
                if delay is None:
                    delay = _backoff_delay(transient_failures, retry_delay)
                    transient_failures += 1
                logger.warning(
                    "telegram_rate_limited",
                    retry_after=delay,
                    attempt=attempt + 1,
                )
                if attempt < total_attempts - 1:
                    time.sleep(delay)
                continue
            # Other HTTP status: bounded exponential backoff.
            transient_failures += 1
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            if attempt < total_attempts - 1:
                time.sleep(_backoff_delay(transient_failures - 1, retry_delay))
                continue
            if rate_limit_hit:
                logger.error(
                    "telegram_dead_letter",
                    reason="rate_limited",
                    attempts=total_attempts,
                    preview=text[:80],
                )
                return False
            raise
        except requests.exceptions.RequestException:
            if attempt < total_attempts - 1:
                time.sleep(_backoff_delay(transient_failures, retry_delay))
                transient_failures += 1
                continue
            raise

    if rate_limit_hit:
        logger.error(
            "telegram_dead_letter",
            reason="rate_limited",
            attempts=total_attempts,
            preview=text[:80],
        )
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
            send_kwargs: dict = {
                "base_url": self.base_url,
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "max_retries": getattr(settings, "NOTIFICATION_MAX_RETRIES", 3),
                "retry_delay": getattr(settings, "NOTIFICATION_RETRY_DELAY", 5),
            }
            limit = getattr(settings, "TELEGRAM_RATE_LIMIT_PER_MINUTE", None)
            if limit is not None:
                send_kwargs["rate_limit_per_minute"] = limit
            sent = self.sender(**send_kwargs)
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
        gate_reasons = [r for r in signal.reasons if any(kw in r for kw in gate_keywords)]
        if gate_reasons:
            lines.append("  🛡️ Uygulanan korumalar:")
            for gr in gate_reasons:
                lines.append(f"    • {gr}")
        else:
            lines.append("  🛡️ Koruma tetiklenmedi")

        # Threshold info — engine owns the threshold, signal carries it.
        # Direction-aware: sells compare against the sell threshold.
        category = categorize_signal(signal)
        if signal.signal_type.is_sell:
            threshold_display = signal.sell_threshold
            threshold_note = "SAT eşik"
            actionable_desc = "actionable" if signal.score <= signal.sell_threshold else "radar"
        else:
            threshold_display = signal.buy_threshold
            threshold_note = "AL eşik"
            actionable_desc = "actionable" if category is SignalCategory.AL else "radar"
        lines.append(
            f"  Skor {signal.score:+.0f} / actionable {threshold_note} {threshold_display}"
            f" → {actionable_desc}"
        )

        return "\n".join(lines)

    def _signal_label(self, signal: Signal) -> str:
        """Return the one-line label for a signal detail message."""
        category = categorize_signal(signal)
        if signal.signal_type.is_sell:
            if signal.score <= signal.sell_threshold:
                return "<b>SAT SİNYALİ</b> (actionable — paper'da pozisyon simüle edilir)"
            return f"{signal.signal_type.value} (henüz actionable DEĞİL, izleme)"
        if category is SignalCategory.AL:
            return "<b>AL SİNYALİ</b> (actionable — paper'da emir simüle edilir)"
        if category is SignalCategory.RADAR:
            return "<b>RADAR / İZLE</b> (henüz actionable DEĞİL — emir YOK, sadece izleme)"
        return f"{signal.signal_type.value}"

    def _build_contribution_block(self, signal: Signal) -> str:
        """Render a compact per-component score summary."""
        if not signal.score_breakdown:
            return ""
        top = signal.top_contributors(count=3)
        if not top:
            return ""
        lines = ["🧮 <b>Katki Dağılımı:</b>"]
        for name, value in top:
            bar = "+" if value >= 0 else ""
            emoji = "▲" if value >= 0 else "▼"
            lines.append(f"  {emoji} {name}: {bar}{value:.0f}")
        return "\n".join(lines)

    def send_signal(self, signal: Signal) -> bool:
        return self.send_message(self._build_signal_message(signal))

    def send_signal_to_group(self, signal: Signal) -> bool:
        """Send a signal to the group using the same detail format as the owner message."""
        return self.send_to_group(self._build_signal_message(signal))

    def _build_signal_message(self, signal: Signal) -> str:
        """Build the canonical Telegram detail message for a signal."""
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

{self._build_contribution_block(signal)}

🔍 <b>Teşhis:</b>
{diagnosis}

⏰ {signal.timestamp.strftime("%d.%m.%Y %H:%M")}
━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Bu bir yatırım tavsiyesi değildir!</i>
"""
        return message.strip()

    def send_scan_summary(self, signals: list[Signal], total_scanned: int) -> bool:
        return self.send_message(self._build_scan_summary_message(signals, total_scanned))

    def send_scan_summary_to_group(self, signals: list[Signal], total_scanned: int) -> bool:
        """Send the canonical scan summary to the configured group."""
        return self.send_to_group(self._build_scan_summary_message(signals, total_scanned))

    def _build_scan_summary_message(self, signals: list[Signal], total_scanned: int) -> str:
        """Build the canonical Telegram summary shared by owner and group."""
        buys = [s for s in signals if categorize_signal(s) is SignalCategory.AL]
        radars = [s for s in signals if categorize_signal(s) is SignalCategory.RADAR]
        sells = [s for s in signals if categorize_signal(s) is SignalCategory.SAT]
        holds = [s for s in signals if categorize_signal(s) is SignalCategory.HOLD]

        top_opportunities = sorted([*buys, *radars], key=lambda s: s.score, reverse=True)[:3]
        top_sells = sorted(sells, key=lambda s: s.score)[:3]

        top_opportunities_text = (
            "\n".join(
                [
                    f"  {'🟢' if categorize_signal(s) is SignalCategory.AL else '🟡'} "
                    f"{settings.TICKER_NAMES.get(s.ticker, s.ticker)}: "
                    f"₺{s.price:.2f} (Skor: {s.score:+.0f}) — "
                    f"{'AL' if categorize_signal(s) is SignalCategory.AL else 'RADAR'}"
                    for s in top_opportunities
                ]
            )
            or "  Yok"
        )

        top_sells_text = (
            "\n".join(
                [
                    f"  {'🔴' if s.score <= s.sell_threshold else '🟠'} {settings.TICKER_NAMES.get(s.ticker, s.ticker)}: "
                    f"₺{s.price:.2f} (Skor: {s.score:+.0f}) "
                    f"— {'SAT (actionable)' if s.score <= s.sell_threshold else 'radar'}"
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
        return message.strip()

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
