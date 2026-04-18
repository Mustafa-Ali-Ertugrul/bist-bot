"""Shared signal models used across strategy, storage, and notification layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import config


class SignalType(Enum):
    STRONG_BUY = "💰 GÜÇLÜ AL"
    BUY = "🟢 AL"
    WEAK_BUY = "🟡 ZAYIF AL"
    HOLD = "⚪ BEKLE"
    WEAK_SELL = "🟠 ZAYIF SAT"
    SELL = "🔴 SAT"
    STRONG_SELL = "🚨 GÜÇLÜ SAT"


@dataclass
class Signal:
    ticker: str
    signal_type: SignalType
    score: float
    price: float
    reasons: list[str] = field(default_factory=list)
    stop_loss: float = 0.0
    target_price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: str = "DÜŞÜK"

    def __str__(self) -> str:
        name = config.TICKER_NAMES.get(self.ticker, self.ticker)
        reasons_str = "\n    ".join(self.reasons)
        return (
            f"\n{'='*50}\n"
            f"📊 {name} ({self.ticker})\n"
            f"{'='*50}\n"
            f"  Sinyal  : {self.signal_type.value}\n"
            f"  Skor    : {self.score:+.1f}/100\n"
            f"  Fiyat   : ₺{self.price:.2f}\n"
            f"  Güven   : {self.confidence}\n"
            f"  Stop-Loss: ₺{self.stop_loss:.2f}\n"
            f"  Hedef   : ₺{self.target_price:.2f}\n"
            f"  Nedenler:\n    {reasons_str}\n"
            f"  Zaman   : {self.timestamp.strftime('%d.%m.%Y %H:%M')}\n"
            f"{'='*50}"
        )
