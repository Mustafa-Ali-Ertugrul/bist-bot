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
    def is_buy(self) -> bool:
        """Return True when this type belongs to the long direction (weak levels included)."""
        return self in {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}

    @property
    def is_sell(self) -> bool:
        """Return True when this type belongs to the short direction (weak levels included)."""
        return self in {SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL}

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


class SignalCategory(Enum):
    AL = "AL"
    RADAR = "RADAR"
    SAT = "SAT"
    HOLD = "HOLD"


def categorize(
    signal_type: SignalType,
    score: float,
    buy_threshold: float = 20.0,
    max_signal_score: float = 33.0,
) -> SignalCategory:
    """Classify a signal into the canonical category (AL / RADAR / SAT / HOLD).

    Rules (in priority order):
    1. Short/sell direction family -> SAT
    2. HOLD type -> HOLD
    3. RADAR type -> RADAR if score > 0 else HOLD
    4. Long/buy direction family:
       - score >= buy_threshold -> AL
       - score > 0 -> RADAR
       - otherwise -> HOLD

    NOTE: Effective score is capped at ``max_signal_score`` (default 33) to prevent
    overconfident high scores from degrading trade performance (per challenge data:
    35+ scores have WR %69.7 but net −497 TL/işlem; 28-33 bandı %76.6 +630 TL).
    """
    effective_score = min(score, max_signal_score)
    if signal_type.is_sell:
        return SignalCategory.SAT
    if signal_type is SignalType.HOLD:
        return SignalCategory.HOLD
    if signal_type is SignalType.RADAR:
        return SignalCategory.RADAR if effective_score > 0 else SignalCategory.HOLD
    if signal_type.is_buy:
        if effective_score >= buy_threshold:
            return SignalCategory.AL
        if effective_score > 0:
            return SignalCategory.RADAR
        return SignalCategory.HOLD
    return SignalCategory.HOLD


def categorize_signal(
    signal: Signal, buy_threshold: float | None = None, max_signal_score: float | None = None
) -> SignalCategory:
    """Categorize a Signal object using its internal buy_threshold unless overridden.

    Parameters
    ----------
    signal : Signal
        The signal to categorize.
    buy_threshold : float, optional
        Override the signal's internal buy_threshold. Defaults to the signal's
        ``buy_threshold`` attribute (default 20.0) or the settings value.
    max_signal_score : float, optional
        Cap the effective score at this value (default 33.0 from settings).
        Scores above this cap are treated as the cap value for categorization,
        preventing overconfident high scores from degrading performance.
    """
    threshold = (
        buy_threshold if buy_threshold is not None else getattr(signal, "buy_threshold", 20.0)
    )
    mss = max_signal_score if max_signal_score is not None else 33.0
    return categorize(signal.signal_type, float(signal.score), threshold, mss)


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
    sell_threshold: float = -20.0
    is_actionable: bool = False
    score_breakdown: dict[str, float] | None = field(default=None)
    """Per-component score contributions for explainability."""
    ema_200: float | None = field(default=None)
    """EMA200 value at signal time (for shadow trend filtering)."""
    ema_200_slope: float | None = field(default=None)
    """Direction of EMA200: >0 rising, <0 falling, 0 flat."""
    record_id: int | None = field(default=None)
    """DB primary key of the persisted SignalRecord (populated by save_signal)."""

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
            sell_threshold=self.sell_threshold,
            is_actionable=self.is_actionable,
            score_breakdown=dict(self.score_breakdown) if self.score_breakdown else None,
            ema_200=self.ema_200,
            ema_200_slope=self.ema_200_slope,
            record_id=self.record_id,
        )

    def top_contributors(self, *, count: int = 3) -> list[tuple[str, float]]:
        """Return the top-scoring components sorted by absolute contribution."""
        if not self.score_breakdown:
            return []
        return sorted(self.score_breakdown.items(), key=lambda kv: abs(kv[1]), reverse=True)[:count]

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
