"""Signal scoring and classification logic for BIST trading ideas."""

import pandas as pd
from enum import Enum
from typing import Any, Optional
import logging

from config import settings
from indicators import TechnicalIndicators
from risk_manager import RiskManager
from signal_models import Signal, SignalType

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class TrendBias(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


def detect_regime(df: pd.DataFrame, lookback: int = 20) -> MarketRegime:
    """Infer the current market regime from trend indicators.

    Args:
        df: Indicator-enriched price dataframe.
        lookback: Reserved lookback window size.

    Returns:
        Detected market regime.
    """
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


class StrategyEngine:
    STRONG_BUY_THRESHOLD = getattr(settings, "STRONG_BUY_THRESHOLD", 40)
    BUY_THRESHOLD = getattr(settings, "BUY_THRESHOLD", 10)
    WEAK_BUY_THRESHOLD = getattr(settings, "WEAK_BUY_THRESHOLD", 0)
    WEAK_SELL_THRESHOLD = getattr(settings, "WEAK_SELL_THRESHOLD", 0)
    SELL_THRESHOLD = getattr(settings, "SELL_THRESHOLD", -10)
    STRONG_SELL_THRESHOLD = getattr(settings, "STRONG_SELL_THRESHOLD", -40)
    MIN_REGIME_PERSISTENCE = 2
    SIDEWAYS_EXTRA_THRESHOLD = 5
    MOMENTUM_CONFIRMATION = 4.0

    def __init__(
        self,
        indicators: Optional[TechnicalIndicators] = None,
        risk_manager: Optional[RiskManager] = None,
    ) -> None:
        """Initialize injectable indicator and risk-management dependencies."""
        self.indicators = indicators or TechnicalIndicators()
        self.risk_manager = risk_manager or RiskManager(
            capital=getattr(settings, "INITIAL_CAPITAL", 8500.0)
        )
        self.STRONG_BUY_THRESHOLD = getattr(settings, "STRONG_BUY_THRESHOLD", 40)
        self.BUY_THRESHOLD = getattr(settings, "BUY_THRESHOLD", 10)
        self.WEAK_BUY_THRESHOLD = getattr(settings, "WEAK_BUY_THRESHOLD", 0)
        self.WEAK_SELL_THRESHOLD = getattr(settings, "WEAK_SELL_THRESHOLD", 0)
        self.SELL_THRESHOLD = getattr(settings, "SELL_THRESHOLD", -10)
        self.STRONG_SELL_THRESHOLD = getattr(settings, "STRONG_SELL_THRESHOLD", -40)

    def _extract_timeframes(self, market_data: pd.DataFrame | dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
        if isinstance(market_data, dict):
            trend_df = market_data.get("trend")
            trigger_df = market_data.get("trigger")
            if trend_df is None or trigger_df is None:
                raise ValueError("Multi-timeframe veri 'trend' ve 'trigger' anahtarlarını içermeli")
            return trend_df, trigger_df, True
        return market_data, market_data, False

    def _get_trend_bias(self, df: pd.DataFrame) -> TrendBias:
        if df is None or len(df) < 30:
            return TrendBias.NEUTRAL

        enriched = self.indicators.add_all(df.copy())
        regime = detect_regime(enriched)
        last = enriched.iloc[-1]
        close = float(last["close"])
        ema_long = last.get(f"ema_{settings.EMA_LONG}")
        plus_di = last.get("plus_di", 0)
        minus_di = last.get("minus_di", 0)

        if regime == MarketRegime.BULL and pd.notna(ema_long) and close >= float(ema_long) and plus_di >= minus_di:
            return TrendBias.LONG
        if regime == MarketRegime.BEAR and pd.notna(ema_long) and close <= float(ema_long) and minus_di >= plus_di:
            return TrendBias.SHORT
        return TrendBias.NEUTRAL

    def _apply_confluence(self, signal_type: SignalType, trend_bias: TrendBias, reasons: list[str]) -> bool:
        long_signals = {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}
        short_signals = {SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL}

        if signal_type in long_signals:
            if trend_bias != TrendBias.LONG:
                reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
                return False
            reasons.append("MTF confluence: günlük trend LONG, 15dk tetik destekliyor")
            return True

        if signal_type in short_signals:
            if trend_bias != TrendBias.SHORT:
                reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
                return False
            reasons.append("MTF confluence: günlük trend SHORT, 15dk tetik destekliyor")
            return True

        return True

    def _check_regime_persistence(self, df: pd.DataFrame, target_regime: "MarketRegime", min_bars: int = 2) -> bool:
        """Check whether a target regime persisted for the latest bars.

        Args:
            df: Indicator-enriched price dataframe.
            target_regime: Regime to verify.
            min_bars: Minimum number of trailing bars to check.

        Returns:
            ``True`` when the target regime persisted.
        """
        if len(df) < min_bars + 1:
            return False
        for i in range(len(df) - min_bars, len(df)):
            sub = df.iloc[: i + 1]
            if detect_regime(sub) != target_regime:
                return False
        return True

    def _check_momentum_confirmation(self, df: pd.DataFrame, threshold: float = 4.0) -> bool:
        """Validate momentum when the primary trend signal is weak.

        Args:
            df: Indicator-enriched price dataframe.
            threshold: Minimum absolute momentum percentage.

        Returns:
            ``True`` when momentum confirmation passes.
        """
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

    def analyze(
        self,
        ticker: str,
        df: pd.DataFrame | dict[str, pd.DataFrame],
        enforce_sector_limit: bool = False,
    ) -> Optional[Signal]:
        """Score a ticker and build a signal when thresholds are met.

        Args:
            ticker: Stock symbol.
            df: Historical price dataframe.
            enforce_sector_limit: Apply sector concentration guard when ``True``.

        Returns:
            A ``Signal`` instance when a non-hold classification is produced,
            otherwise ``None``.
        """
        trend_df, trigger_df, multi_timeframe = self._extract_timeframes(df)

        if trigger_df is None or len(trigger_df) < 30:
            logger.warning(f"  {ticker}: Yetersiz veri ({len(trigger_df) if trigger_df is not None else 0} mum)")
            return None

        df = self.indicators.add_all(trigger_df.copy())
        trend_bias = self._get_trend_bias(trend_df) if multi_timeframe and getattr(settings, "MTF_ENABLED", True) else TrendBias.NEUTRAL

        last = df.iloc[-1]
        prev = df.iloc[-2]
        score = 0.0
        reasons = []

        adx = last.get("adx")
        if pd.notna(adx):
            if adx < getattr(settings, "ADX_THRESHOLD", 20):
                logger.debug(f"  {ticker}: ADX düşük ({adx:.1f}) - Trend yok, sinyal üretme")
                return None

        regime = detect_regime(df)
        if regime == MarketRegime.SIDEWAYS:
            reasons.append("Piyasa rejimi yatay - skor etkisi azaltıldı")

        ema_long = last.get(f"ema_{settings.EMA_LONG}")
        if pd.notna(ema_long):
            price = last["close"]
            above_ema = price > ema_long
            last_above_ema = prev["close"] > prev.get(f"ema_{settings.EMA_LONG}", ema_long)
            if above_ema and not last_above_ema:
                reasons.append(f"Fiyat EMA{settings.EMA_LONG}'i kesti (yukarı)")
            elif above_ema:
                if adx >= getattr(settings, "ADX_THRESHOLD", 20):
                    score += 10
                    reasons.append(f"yükseliş trendi (EMA{settings.EMA_LONG} üzerinde)")
            elif not above_ema and last_above_ema:
                reasons.append(f"Fiyat EMA{settings.EMA_LONG}'i kesti (aşağı)")

        volume_sma_20 = last.get("volume_sma_20")
        volume = last.get("volume")
        if pd.notna(volume_sma_20) and pd.notna(volume):
            vol_ratio = volume / volume_sma_20
            min_vol_ratio = getattr(settings, "VOLUME_CONFIRM_MULTIPLIER", 1.5)
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
            sma_fast = last.get(f"sma_{settings.SMA_FAST}")
            sma_slow = last.get(f"sma_{settings.SMA_SLOW}")
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

        if signal_type in {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}:
            risk_levels = self.risk_manager.apply_portfolio_risk(ticker, df, risk_levels)
            if risk_levels.blocked_by_correlation or risk_levels.position_size <= 0:
                logger.debug(f"  {ticker}: portföy riski nedeniyle sinyal atlandı")
                return None
        
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
        signal.reasons.append(
            f"Pozisyon: {risk_levels.position_size} lot | Risk Bütçesi: ₺{risk_levels.risk_budget_tl:.2f}"
        )
        signal.reasons.append(
            f"Volatilite throttle: x{risk_levels.volatility_scale:.2f} | ATR%: %{risk_levels.atr_pct*100:.2f}"
        )
        if risk_levels.correlated_tickers:
            signal.reasons.append(
                f"Korelasyon limiti: x{risk_levels.correlation_scale:.2f} | İlişkili: {', '.join(risk_levels.correlated_tickers)}"
            )

        if multi_timeframe and getattr(settings, "MTF_ENABLED", True):
            if not self._apply_confluence(signal.signal_type, trend_bias, signal.reasons):
                logger.debug(f"  {ticker}: MTF confluence nedeniyle sinyal atlandı")
                return None

        if signal_type in {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}:
            self.risk_manager.register_position(ticker, df)

        return signal

    def scan_all(
        self,
        data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]]
    ) -> list[Signal]:
        """Analyze all fetched ticker data and return sorted signals.

        Args:
            data: Mapping of ticker symbols to price dataframes.

        Returns:
            Sorted list of generated signals.
        """
        signals = []
        self.risk_manager.reset_sectors()
        self.risk_manager.reset_portfolio()

        for ticker, df in data.items():
            signal = self.analyze(ticker, df, enforce_sector_limit=True)
            if signal:
                signals.append(signal)

        signals.sort(key=lambda s: s.score, reverse=True)

        return signals

    def get_actionable_signals(
        self,
        signals: list[Signal]
    ) -> list[Signal]:
        """Filter out hold signals from the signal list.

        Args:
            signals: Full signal list.

        Returns:
            Only actionable signals.
        """
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
