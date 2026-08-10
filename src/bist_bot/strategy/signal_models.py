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
        by_name = SignalType.__members__.get(value.upper())
        if by_name is not None:
            return by_name
        for st in SignalType:
            if st.display == value:
                return st
        raise ValueError(f"Unknown signal type: {value}")


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime and reject ambiguous naive values."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Naive datetime is not allowed; provide an explicit timezone")
    if value.tzinfo is UTC:
        return value
    return value.astimezone(UTC)


def _make_expires_at(timestamp: datetime) -> datetime:
    ttl = getattr(settings, "SIGNAL_TTL_MINUTES", 60)
    return ensure_utc(timestamp) + timedelta(minutes=ttl)


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence: str = "confidence.low"
    agreement_ratio: float | None = field(default=None)
    expires_at: datetime | None = field(default=None)
    buy_threshold: float = 20.0
    is_actionable: bool = False
    score_breakdown: dict[str, float] | None = field(default=None)
    """Per-component score contributions for explainability."""

    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = _make_expires_at(self.timestamp)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current_time = ensure_utc(now or datetime.now(UTC))
        return current_time >= ensure_utc(self.expires_at)

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
            agreement_ratio=self.agreement_ratio,
            expires_at=self.expires_at,
            buy_threshold=self.buy_threshold,
            is_actionable=self.is_actionable,
            score_breakdown=dict(self.score_breakdown) if self.score_breakdown else None,
        )

    def top_contributors(self, *, count: int = 3) -> list[tuple[str, float]]:
        """Return the top-scoring components sorted by absolute contribution."""
        if not self.score_breakdown:
            return []
        return sorted(
            self.score_breakdown.items(), key=lambda kv: abs(kv[1]), reverse=True
        )[:count]

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
