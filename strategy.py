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


class MarketRegime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


def detect_regime(df: pd.DataFrame, lookback: int = 20) -> MarketRegime:
    if df is None or len(df) < 50:
        return MarketRegime.UNKNOWN

    last = df.iloc[-1]
    adx = last.get("adx", 0)
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)
    close = float(last["close"])

    TREND_ADX = 20
    WEAK_ADX = 15
    DI_RATIO = 1.25

    sma_20 = float(df["close"].tail(20).mean())
    momentum = (close - sma_20) / sma_20 * 100

    if adx >= TREND_ADX:
        if plus_di > minus_di * DI_RATIO:
            return MarketRegime.BULL
        elif minus_di > plus_di * DI_RATIO:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    elif adx >= WEAK_ADX:
        if momentum > 3 and plus_di > minus_di:
            return MarketRegime.BULL
        elif momentum < -3 and minus_di > plus_di:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    return MarketRegime.SIDEWAYS


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
    STRONG_BUY_THRESHOLD = getattr(config, "STRONG_BUY_THRESHOLD", 40)
    BUY_THRESHOLD = 15
    WEAK_BUY_THRESHOLD = getattr(config, "WEAK_BUY_THRESHOLD", 0)
    WEAK_SELL_THRESHOLD = getattr(config, "WEAK_SELL_THRESHOLD", 0)
    SELL_THRESHOLD = getattr(config, "SELL_THRESHOLD", -10)
    STRONG_SELL_THRESHOLD = getattr(config, "STRONG_SELL_THRESHOLD", -40)
    MIN_REGIME_PERSISTENCE = 2
    SIDEWAYS_EXTRA_THRESHOLD = 5
    MOMENTUM_CONFIRMATION = 4.0

    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.risk_manager = RiskManager(capital=getattr(config, "INITIAL_CAPITAL", 8500.0))
        self.STRONG_BUY_THRESHOLD = getattr(config, "STRONG_BUY_THRESHOLD", self.STRONG_BUY_THRESHOLD)
        self.BUY_THRESHOLD = 15
        self.WEAK_BUY_THRESHOLD = getattr(config, "WEAK_BUY_THRESHOLD", self.WEAK_BUY_THRESHOLD)
        self.WEAK_SELL_THRESHOLD = getattr(config, "WEAK_SELL_THRESHOLD", self.WEAK_SELL_THRESHOLD)
        self.SELL_THRESHOLD = getattr(config, "SELL_THRESHOLD", self.SELL_THRESHOLD)
        self.STRONG_SELL_THRESHOLD = getattr(config, "STRONG_SELL_THRESHOLD", self.STRONG_SELL_THRESHOLD)

    def _check_regime_persistence(self, df: pd.DataFrame, target_regime: "MarketRegime", min_bars: int = 2) -> bool:
        if len(df) < min_bars + 1:
            return False
        for i in range(len(df) - min_bars, len(df)):
            sub = df.iloc[: i + 1]
            if detect_regime(sub) != target_regime:
                return False
        return True

    def _check_momentum_confirmation(self, df: pd.DataFrame, threshold: float = 4.0) -> bool:
        if len(df) < 20:
            return True
        last = df.iloc[-1]
        adx = last.get("adx", 0)
        plus_di = last.get("plus_di", 0)
        minus_di = last.get("minus_di", 0)
        if adx >= 20:
            return True
        if abs(plus_di - minus_di) >= 5:
            return True
        sma_20 = float(df["close"].tail(20).mean())
        momentum = (float(last["close"]) - sma_20) / sma_20 * 100
        return abs(momentum) >= threshold

    def analyze(self, ticker: str, df: pd.DataFrame, enforce_sector_limit: bool = False) -> Optional[Signal]:
        if df is None or len(df) < 30:
            logger.warning(f"  {ticker}: Yetersiz veri ({len(df) if df is not None else 0} mum)")
            return None

        df = self.indicators.add_all(df)

        last = df.iloc[-1]
        prev = df.iloc[-2]
        score = 0.0
        reasons = []

        adx = last.get("adx")
        if pd.notna(adx):
            if adx < getattr(config, "ADX_THRESHOLD", 20):
                logger.debug(f"  {ticker}: ADX düşük ({adx:.1f}) - Trend yok, sinyal üretme")
                return None

        regime = detect_regime(df)
        if regime == MarketRegime.SIDEWAYS:
            reasons.append("Piyasa rejimi yatay - skor etkisi azaltıldı")

        ema_long = last.get(f"ema_{config.EMA_LONG}")
        if pd.notna(ema_long):
            price = last["close"]
            above_ema = price > ema_long
            last_above_ema = prev["close"] > prev.get(f"ema_{config.EMA_LONG}", ema_long)
            if above_ema and not last_above_ema:
                reasons.append(f"Fiyat EMA{config.EMA_LONG}'i kesti (yukarı)")
            elif above_ema:
                if adx >= getattr(config, "ADX_THRESHOLD", 20):
                    score += 10
                    reasons.append(f"yükseliş trendi (EMA{config.EMA_LONG} üzerinde)")
            elif not above_ema and last_above_ema:
                reasons.append(f"Fiyat EMA{config.EMA_LONG}'i kesti (aşağı)")

        volume_sma_20 = last.get("volume_sma_20")
        volume = last.get("volume")
        if pd.notna(volume_sma_20) and pd.notna(volume):
            vol_ratio = volume / volume_sma_20
            min_vol_ratio = getattr(config, "VOLUME_CONFIRM_MULTIPLIER", 1.5)
            if vol_ratio >= min_vol_ratio:
                score += 8
                reasons.append(f"Hacim onayı ({vol_ratio:.1f}x ort)")

        rsi = last.get("rsi")
        if pd.notna(rsi):
            if rsi < 25:
                score += 18
                reasons.append(f"RSI çok düşük ({rsi:.1f}) → Aşırı satım")
            elif rsi < 30:
                score += 14
                reasons.append(f"RSI düşük ({rsi:.1f}) → Satım bölgesi")
            elif rsi < 40:
                score += 7
                reasons.append(f"RSI düşük-nötr ({rsi:.1f})")
            elif rsi > 80:
                score -= 18
                reasons.append(f"RSI çok yüksek ({rsi:.1f}) → Aşırı alım")
            elif rsi > 70:
                score -= 14
                reasons.append(f"RSI yüksek ({rsi:.1f}) → Alım bölgesi")
            elif rsi > 60:
                score -= 4
                reasons.append(f"RSI yüksek-nötr ({rsi:.1f})")
            else:
                reasons.append(f"RSI nötr ({rsi:.1f})")

        stoch_k = last.get("stoch_k")
        stoch_d = last.get("stoch_d")
        if pd.notna(stoch_k) and pd.notna(stoch_d):
            stoch_cross = last.get("stoch_cross", "NONE")
            if stoch_cross == "BULLISH":
                score += 8
                reasons.append(f"Stochastic Bullish Cross (K:{stoch_k:.0f}, D:{stoch_d:.0f})")
            elif stoch_cross == "BEARISH":
                score -= 8
                reasons.append(f"Stochastic Bearish Cross (K:{stoch_k:.0f}, D:{stoch_d:.0f})")
            
            if stoch_k < 20 and stoch_d < 20:
                score += 6
                reasons.append(f"Stochastic aşırı satım bölgesi (K:{stoch_k:.0f})")
            elif stoch_k > 80 and stoch_d > 80:
                score -= 6
                reasons.append(f"Stochastic aşırı alım bölgesi (K:{stoch_k:.0f})")
            
            if stoch_k > stoch_d and stoch_k < 50:
                score += 3
                reasons.append(f"Stochastic yükseliş eğilimi")
            elif stoch_k < stoch_d and stoch_k > 50:
                score -= 3
                reasons.append(f"Stochastic düşüş eğilimi")

        cci = last.get("cci")
        if pd.notna(cci):
            if cci < -100:
                score += 8
                reasons.append(f"CCI aşırı satım ({cci:.0f})")
            elif cci < -50:
                score += 4
                reasons.append(f"CCI düşük ({cci:.0f})")
            elif cci > 100:
                score -= 8
                reasons.append(f"CCI aşırı alım ({cci:.0f})")
            elif cci > 50:
                score -= 4
                reasons.append(f"CCI yüksek ({cci:.0f})")

        sma_cross = last.get("sma_cross", "NONE")
        if sma_cross == "GOLDEN_CROSS":
            score += 12
            reasons.append("SMA Golden Cross ✨ → Yükseliş sinyali")
        elif sma_cross == "DEATH_CROSS":
            score -= 12
            reasons.append("SMA Death Cross 💀 → Düşüş sinyali")
        else:
            sma_fast = last.get(f"sma_{config.SMA_FAST}")
            sma_slow = last.get(f"sma_{config.SMA_SLOW}")
            if pd.notna(sma_fast) and pd.notna(sma_slow):
                if sma_fast > sma_slow:
                    score += 3
                    reasons.append(f"SMA trend yukarı")
                else:
                    score -= 3
                    reasons.append(f"SMA trend aşağı")

        ema_cross = last.get("ema_cross", "NONE")
        if ema_cross == "BULLISH":
            score += 10
            reasons.append("EMA Bullish Cross ⚡ → Hızlı yükseliş")
        elif ema_cross == "BEARISH":
            score -= 10
            reasons.append("EMA Bearish Cross ⚡ → Hızlı düşüş")

        macd_cross = last.get("macd_cross", "NONE")
        macd_hist = last.get("macd_histogram")
        macd_hist_inc = last.get("macd_hist_increasing", False)

        if macd_cross == "BULLISH":
            score += 12
            reasons.append("MACD Bullish Crossover 📈")
        elif macd_cross == "BEARISH":
            score -= 12
            reasons.append("MACD Bearish Crossover 📉")

        if pd.notna(macd_hist):
            if macd_hist > 0 and macd_hist_inc:
                score += 5
                reasons.append(f"MACD Histogram güçleniyor ({macd_hist:.2f})")
            elif macd_hist > 0:
                score += 3
                reasons.append(f"MACD Histogram pozitif ({macd_hist:.2f})")
            elif macd_hist < 0 and not macd_hist_inc:
                score -= 5
                reasons.append(f"MACD Histogram zayıflıyor ({macd_hist:.2f})")
            else:
                score -= 3
                reasons.append(f"MACD Histogram negatif ({macd_hist:.2f})")

        plus_di = last.get("plus_di")
        minus_di = last.get("minus_di")
        if pd.notna(adx) and pd.notna(plus_di) and pd.notna(minus_di):
            if adx > 25:
                if plus_di > minus_di:
                    score += 8
                    reasons.append(f"Güçlü yükseliş trendi (ADX:{adx:.0f}, +DI>{minus_di:.0f})")
                else:
                    score -= 8
                    reasons.append(f"Güçlü düşüş trendi (ADX:{adx:.0f}, -DI>{plus_di:.0f})")
            else:
                if plus_di > minus_di:
                    score += 3
                    reasons.append(f"Zayıf yükseliş trendi (ADX:{adx:.0f})")
                else:
                    score -= 3
                    reasons.append(f"Zayıf düşüş trendi (ADX:{adx:.0f})")

        di_cross = last.get("di_cross", "NONE")
        if di_cross == "BULLISH":
            score += 6
            reasons.append("+DI/-DI Bullish Cross")
        elif di_cross == "BEARISH":
            score -= 6
            reasons.append("+DI/-DI Bearish Cross")

        bb_pos = last.get("bb_position", "MIDDLE")
        bb_pct = last.get("bb_percent")
        bb_squeeze = last.get("bb_squeeze", False)

        if bb_pos == "BELOW_LOWER":
            score += 10
            reasons.append("Fiyat Bollinger alt bandının altında → Alım fırsatı")
        elif bb_pos == "ABOVE_UPPER":
            score -= 10
            reasons.append("Fiyat Bollinger üst bandının üstünde → Aşırı uzamış")
        elif pd.notna(bb_pct):
            if bb_pct < 0.2:
                score += 5
                reasons.append(f"Bollinger %B düşük ({bb_pct:.2f})")
            elif bb_pct > 0.8:
                score -= 5
                reasons.append(f"Bollinger %B yüksek ({bb_pct:.2f})")
        
        if bb_squeeze:
            reasons.append("Bollinger Squeeze → Patlama bekleniyor ⚠️")

        vol_spike = last.get("volume_spike", False)
        vol_ratio = last.get("volume_ratio", 1.0)
        pv_confirm = last.get("price_volume_confirm", False)
        vol_trend = last.get("volume_trend", "FLAT")

        if vol_spike:
            price_change = last["close"] - df.iloc[-2]["close"]
            if price_change > 0:
                score += 8
                reasons.append(f"Hacim patlaması + yükseliş ({vol_ratio:.1f}x)")
            else:
                score -= 8
                reasons.append(f"Hacim patlaması + düşüş ({vol_ratio:.1f}x)")

        if pv_confirm:
            score += 2
            reasons.append("Fiyat-Hacim uyumu ✓")
        
        if vol_trend == "INCREASING":
            score += 2
            reasons.append("Hacim artıyor 📊")
        elif vol_trend == "DECREASING":
            score -= 2
            reasons.append("Hacim azalıyor 📊")

        obv_trend = last.get("obv_trend", "FLAT")
        if obv_trend == "UP":
            score += 4
            reasons.append("OBV yükseliş trendi → Akış var")
        elif obv_trend == "DOWN":
            score -= 4
            reasons.append("OBV düşüş trendi → Çıkış var")

        dist_support = last.get("dist_to_support_pct", 50)
        dist_resist = last.get("dist_to_resistance_pct", 50)

        if pd.notna(dist_support) and dist_support < 2:
            score += 6
            reasons.append(f"Fiyat desteğe yakın (%{dist_support:.1f})")
        elif pd.notna(dist_resist) and dist_resist < 2:
            score -= 6
            reasons.append(f"Fiyat dirence yakın (%{dist_resist:.1f})")

        rsi_div = last.get("rsi_divergence", "NONE")
        if rsi_div == "BULLISH":
            score += 15
            reasons.append("🔥 RSI Bullish Divergence → Güçlü dönüş sinyali")
        elif rsi_div == "BEARISH":
            score -= 15
            reasons.append("🔥 RSI Bearish Divergence → Güçlü dönüş sinyali")

        macd_div = last.get("macd_divergence", "NONE")
        if macd_div == "BULLISH":
            score += 12
            reasons.append("🔥 MACD Bullish Divergence → Güçlü dönüş sinyali")
        elif macd_div == "BEARISH":
            score -= 12
            reasons.append("🔥 MACD Bearish Divergence → Güçlü dönüş sinyali")

        if regime == MarketRegime.SIDEWAYS:
            score *= 0.6
            if abs(score) < self.BUY_THRESHOLD:
                logger.debug(f"  {ticker}: Yatay piyasada skor zayıf ({score:.1f}) - sinyal yok")
                return None

        if score > 0 and not self._check_momentum_confirmation(df, self.MOMENTUM_CONFIRMATION):
            if abs(score) < self.BUY_THRESHOLD + self.SIDEWAYS_EXTRA_THRESHOLD:
                logger.debug(f"  {ticker}: Momentum onaysiz, sinyal atlandi")
                return None

        score = max(-100, min(100, score))

        if score == 0:
            return None

        if score >= self.STRONG_BUY_THRESHOLD:
            signal_type = SignalType.STRONG_BUY
            confidence = "YÜKSEK"
        elif score >= self.BUY_THRESHOLD:
            signal_type = SignalType.BUY
            confidence = "ORTA"
        elif score > max(0, self.WEAK_BUY_THRESHOLD):
            signal_type = SignalType.WEAK_BUY
            confidence = "DÜŞÜK"
        elif score <= self.STRONG_SELL_THRESHOLD:
            signal_type = SignalType.STRONG_SELL
            confidence = "YÜKSEK"
        elif score <= self.SELL_THRESHOLD:
            signal_type = SignalType.SELL
            confidence = "ORTA"
        elif score < min(0, self.WEAK_SELL_THRESHOLD):
            signal_type = SignalType.WEAK_SELL
            confidence = "DÜŞÜK"
        else:
            return None

        if signal_type in {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}:
            if enforce_sector_limit and not self.risk_manager.check_sector_limit(ticker):
                logger.debug(f"  {ticker}: sektör limiti nedeniyle sinyal atlandı")
                return None

        price = float(last["close"])
        risk_levels = self.risk_manager.calculate(df)
        
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
        self.risk_manager.reset_sectors()

        for ticker, df in data.items():
            signal = self.analyze(ticker, df, enforce_sector_limit=True)
            if signal:
                signals.append(signal)

        signals.sort(key=lambda s: s.score, reverse=False)

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
