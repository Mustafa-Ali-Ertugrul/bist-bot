import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import logging

import config
from indicators import TechnicalIndicators
from risk_manager import RiskManager

logger = logging.getLogger(__name__)


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

    def __str__(self):
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


class StrategyEngine:
    STRONG_BUY_THRESHOLD = 60
    BUY_THRESHOLD = 35
    WEAK_BUY_THRESHOLD = 15
    WEAK_SELL_THRESHOLD = -15
    SELL_THRESHOLD = -35
    STRONG_SELL_THRESHOLD = -60

    def __init__(self):
        self.indicators = TechnicalIndicators()

    def analyze(self, ticker: str, df: pd.DataFrame) -> Optional[Signal]:
        if df is None or len(df) < 30:
            logger.warning(f"  {ticker}: Yetersiz veri ({len(df) if df is not None else 0} mum)")
            return None

        df = self.indicators.add_all(df)

        last = df.iloc[-1]
        score = 0.0
        reasons = []

        rsi = last.get("rsi")
        if pd.notna(rsi):
            if rsi < 25:
                score += 25
                reasons.append(f"RSI çok düşük ({rsi:.1f}) → Aşırı satım")
            elif rsi < 30:
                score += 20
                reasons.append(f"RSI düşük ({rsi:.1f}) → Satım bölgesi")
            elif rsi < 40:
                score += 10
                reasons.append(f"RSI düşük-nötr ({rsi:.1f})")
            elif rsi > 80:
                score -= 25
                reasons.append(f"RSI çok yüksek ({rsi:.1f}) → Aşırı alım")
            elif rsi > 70:
                score -= 20
                reasons.append(f"RSI yüksek ({rsi:.1f}) → Alım bölgesi")
            elif rsi > 60:
                score -= 5
                reasons.append(f"RSI yüksek-nötr ({rsi:.1f})")
            else:
                reasons.append(f"RSI nötr ({rsi:.1f})")

        sma_cross = last.get("sma_cross", "NONE")
        if sma_cross == "GOLDEN_CROSS":
            score += 20
            reasons.append("SMA Golden Cross ✨ → Yükseliş sinyali")
        elif sma_cross == "DEATH_CROSS":
            score -= 20
            reasons.append("SMA Death Cross 💀 → Düşüş sinyali")
        else:
            sma_fast = last.get(f"sma_{config.SMA_FAST}")
            sma_slow = last.get(f"sma_{config.SMA_SLOW}")
            if pd.notna(sma_fast) and pd.notna(sma_slow):
                if sma_fast > sma_slow:
                    score += 5
                    reasons.append(f"SMA trend yukarı (SMA{config.SMA_FAST} > SMA{config.SMA_SLOW})")
                else:
                    score -= 5
                    reasons.append(f"SMA trend aşağı (SMA{config.SMA_FAST} < SMA{config.SMA_SLOW})")

        macd_cross = last.get("macd_cross", "NONE")
        macd_hist = last.get("macd_histogram")

        if macd_cross == "BULLISH":
            score += 20
            reasons.append("MACD Bullish Crossover 📈")
        elif macd_cross == "BEARISH":
            score -= 20
            reasons.append("MACD Bearish Crossover 📉")

        if pd.notna(macd_hist):
            if macd_hist > 0:
                score += 5
                reasons.append(f"MACD Histogram pozitif ({macd_hist:.2f})")
            else:
                score -= 5
                reasons.append(f"MACD Histogram negatif ({macd_hist:.2f})")

        bb_pos = last.get("bb_position", "MIDDLE")
        bb_pct = last.get("bb_percent")

        if bb_pos == "BELOW_LOWER":
            score += 15
            reasons.append("Fiyat Bollinger alt bandının altında → Alım fırsatı")
        elif bb_pos == "ABOVE_UPPER":
            score -= 15
            reasons.append("Fiyat Bollinger üst bandının üstünde → Aşırı uzamış")
        elif pd.notna(bb_pct):
            if bb_pct < 0.2:
                score += 8
                reasons.append(f"Bollinger %B düşük ({bb_pct:.2f})")
            elif bb_pct > 0.8:
                score -= 8
                reasons.append(f"Bollinger %B yüksek ({bb_pct:.2f})")

        vol_spike = last.get("volume_spike", False)
        vol_ratio = last.get("volume_ratio", 1.0)
        pv_confirm = last.get("price_volume_confirm", False)

        if vol_spike:
            price_change = last["close"] - df.iloc[-2]["close"]
            if price_change > 0:
                score += 10
                reasons.append(
                    f"Hacim patlaması + fiyat yükselişi "
                    f"(hacim {vol_ratio:.1f}x ortalama)"
                )
            else:
                score -= 10
                reasons.append(
                    f"Hacim patlaması + fiyat düşüşü "
                    f"(hacim {vol_ratio:.1f}x ortalama)"
                )

        if pv_confirm:
            score += 3
            reasons.append("Fiyat-Hacim uyumu mevcut ✓")

        dist_support = last.get("dist_to_support_pct", 50)
        dist_resist = last.get("dist_to_resistance_pct", 50)

        if pd.notna(dist_support) and dist_support < 2:
            score += 10
            reasons.append(
                f"Fiyat desteğe çok yakın "
                f"(%{dist_support:.1f} uzaklık)"
            )
        elif pd.notna(dist_resist) and dist_resist < 2:
            score -= 10
            reasons.append(
                f"Fiyat dirence çok yakın "
                f"(%{dist_resist:.1f} uzaklık)"
            )

        score = max(-100, min(100, score))

        if score >= self.STRONG_BUY_THRESHOLD:
            signal_type = SignalType.STRONG_BUY
            confidence = "YÜKSEK"
        elif score >= self.BUY_THRESHOLD:
            signal_type = SignalType.BUY
            confidence = "ORTA"
        elif score >= self.WEAK_BUY_THRESHOLD:
            signal_type = SignalType.WEAK_BUY
            confidence = "DÜŞÜK"
        elif score <= self.STRONG_SELL_THRESHOLD:
            signal_type = SignalType.STRONG_SELL
            confidence = "YÜKSEK"
        elif score <= self.SELL_THRESHOLD:
            signal_type = SignalType.SELL
            confidence = "ORTA"
        elif score <= self.WEAK_SELL_THRESHOLD:
            signal_type = SignalType.WEAK_SELL
            confidence = "DÜŞÜK"
        else:
            signal_type = SignalType.HOLD
            confidence = "—"

        price = float(last["close"])
        
        rm = RiskManager(capital=8500)
        risk_levels = rm.calculate(df)
        
        stop_loss = risk_levels.final_stop
        target_price = risk_levels.final_target
        
        signal = Signal(
            ticker=ticker,
            signal_type=signal_type,
            score=score,
            price=price,
            reasons=reasons,
            stop_loss=round(stop_loss, 2),
            target_price=round(target_price, 2),
            confidence=risk_levels.confidence if risk_levels.confidence != "DÜŞÜK" else confidence,
        )
        
        signal.reasons.append(
            f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}"
        )

        return signal

    def scan_all(
        self,
        data: dict[str, pd.DataFrame]
    ) -> list[Signal]:
        signals = []

        for ticker, df in data.items():
            signal = self.analyze(ticker, df)
            if signal:
                signals.append(signal)

        signals.sort(key=lambda s: s.score, reverse=True)

        return signals

    def get_actionable_signals(
        self,
        signals: list[Signal]
    ) -> list[Signal]:
        return [s for s in signals if s.signal_type != SignalType.HOLD]


if __name__ == "__main__":
    from data_fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    engine = StrategyEngine()

    df = fetcher.fetch_single("THYAO.IS", period="6mo")
    if df is not None:
        signal = engine.analyze("THYAO.IS", df)
        if signal:
            print(signal)

    print("\n🔍 Tam Watchlist Taraması:")
    all_data = fetcher.fetch_all()
    signals = engine.scan_all(all_data)

    for s in signals:
        if s.signal_type != SignalType.HOLD:
            print(s)
