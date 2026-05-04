"""Shared signal models used across strategy, scanner, storage, and notification layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from bist_bot.config.settings import settings
from bist_bot.locales import get_message


class SignalType(Enum):
    STRONG_BUY = "💰 GÜÇLÜ AL"
    BUY = "🟢 AL"
    WEAK_BUY = "🟡 ZAYIF AL"
    HOLD = "⚪ BEKLE"
    RADAR = "🔭 İZLE"
    WEAK_SELL = "🟠 ZAYIF SAT"
    SELL = "🔴 SAT"
    STRONG_SELL = "🚨 GÜÇLÜ SAT"

    @property
    def key(self) -> str:
        key_map = {
            "STRONG_BUY": "signal.strong_buy",
            "BUY": "signal.buy",
            "WEAK_BUY": "signal.weak_buy",
            "HOLD": "signal.hold",
            "RADAR": "signal.radar",
            "WEAK_SELL": "signal.weak_sell",
            "SELL": "signal.sell",
            "STRONG_SELL": "signal.strong_sell",
        }
        return key_map.get(self.name, self.name)

    @property
    def display(self) -> str:
        from bist_bot.locales import DEFAULT_LOCALE

        return get_message(self.key, DEFAULT_LOCALE)

    @staticmethod
    def from_value(value: str) -> SignalType:
        try:
            return SignalType(value)
        except ValueError:
            pass
        for st in SignalType:
            if st.display == value:
                return st
        raise ValueError(f"Unknown signal type: {value}")


def _make_expires_at(timestamp: datetime) -> datetime:
    ttl = getattr(settings, "SIGNAL_TTL_MINUTES", 60)
    if timestamp.tzinfo is None:
        return timestamp + timedelta(minutes=ttl)
    return timestamp + timedelta(minutes=ttl)


@dataclass
class Signal:
    ticker: str
    signal_type: SignalType
    score: float
    price: float
    reasons: list[str] = field(default_factory=list)
    stop_loss: float = 0.0
    target_price: float = 0.0
    position_size: int | None = None
    signal_probability: float | None = None
    kelly_fraction: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: str = "confidence.low"
    expires_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = _make_expires_at(self.timestamp)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        if now is None:
            now = datetime.now(UTC)
        expires = self.expires_at
        if expires.tzinfo is None and now.tzinfo is not None:
            expires = expires.replace(tzinfo=UTC)
        elif expires.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now >= expires

    @property
    def confidence_key(self) -> str:
        return self.confidence

    @property
    def confidence_display(self) -> str:
        return get_message(self.confidence)

    def with_locale(self, locale: str) -> Signal:
        return Signal(
            ticker=self.ticker,
            signal_type=self.signal_type,
            score=self.score,
            price=self.price,
            reasons=self.reasons.copy(),
            stop_loss=self.stop_loss,
            target_price=self.target_price,
            position_size=self.position_size,
            signal_probability=self.signal_probability,
            kelly_fraction=self.kelly_fraction,
            timestamp=self.timestamp,
            confidence=self.confidence,
            expires_at=self.expires_at,
        )

    def __str__(self) -> str:
        name = settings.TICKER_NAMES.get(self.ticker, self.ticker)
        reasons_str = "\n    ".join(self.reasons)
        return (
            f"\n{'=' * 50}\n"
            f"📊 {name} ({self.ticker})\n"
            f"{'=' * 50}\n"
            f"  Sinyal  : {self.signal_type.display}\n"
            f"  Skor    : {self.score:+.1f}/100\n"
            f"  Fiyat   : ₺{self.price:.2f}\n"
            f"  Güven   : {self.confidence_display}\n"
            f"  Olasılık: %{(self.signal_probability or 0.0) * 100:.1f}\n"
            f"  Stop-Loss: ₺{self.stop_loss:.2f}\n"
            f"  Hedef   : ₺{self.target_price:.2f}\n"
            f"  Lot     : {self.position_size if self.position_size is not None else '-'}\n"
            f"  Kelly   : %{(self.kelly_fraction or 0.0) * 100:.2f}\n"
            f"  Nedenler:\n    {reasons_str}\n"
            f"  Zaman   : {self.timestamp.strftime('%d.%m.%Y %H:%M')}\n"
            f"{'=' * 50}"
        )
