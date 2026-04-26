"""Signal scoring and classification logic for BIST trading ideas."""

import logging
from contextlib import AbstractContextManager
from typing import Any, cast

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.risk import RiskManager
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import (
    MarketRegime,
    TrendBias,
    apply_confluence,
    check_momentum_confirmation,
    detect_regime,
    get_trend_bias,
)
from bist_bot.strategy.scoring import (
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)
from bist_bot.strategy.base import BaseStrategy
from bist_bot.strategy.signal_models import Signal, SignalType

logger = logging.getLogger(__name__)


class StrategyEngine:
    def __init__(
        self,
        indicators: TechnicalIndicators | None = None,
        risk_manager: RiskManager | None = None,
        params: StrategyParams | None = None,
        meta_model: Any | None = None,
    ) -> None:
        """Initialize injectable indicator and risk-management dependencies."""
        self.indicators = indicators or TechnicalIndicators()
        self.risk_manager = risk_manager or RiskManager(
            capital=getattr(settings, "INITIAL_CAPITAL", 100000.0)
        )
        self.params = params or StrategyParams()
        self.meta_model = meta_model
        self._strategies: dict[str, BaseStrategy] = {}
        self.STRONG_BUY_THRESHOLD = self.params.strong_buy_threshold
        self.BUY_THRESHOLD = self.params.buy_threshold
        self.WEAK_BUY_THRESHOLD = self.params.weak_buy_threshold
        self.WEAK_SELL_THRESHOLD = self.params.weak_sell_threshold
        self.SELL_THRESHOLD = self.params.sell_threshold
        self.STRONG_SELL_THRESHOLD = self.params.strong_sell_threshold
        self.SIDEWAYS_EXTRA_THRESHOLD = self.params.sideways_extra_threshold
        self.MOMENTUM_CONFIRMATION = self.params.momentum_confirmation_threshold

    def register_strategy(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def unregister_strategy(self, name: str) -> bool:
        if name in self._strategies:
            del self._strategies[name]
            return True
        return False

    def scan_with_plugins(self, market_data: dict[str, pd.DataFrame]) -> list[Signal]:
        if not self._strategies:
            return self.scan_all(market_data)
        all_signals: list[Signal] = []
        for ticker, df in market_data.items():
            for strategy in self._strategies.values():
                signal = strategy.analyze(ticker, df)
                if signal:
                    all_signals.append(signal)
        seen: dict[str, Signal] = {}
        for s in all_signals:
            if s.ticker not in seen or s.score > seen[s.ticker].score:
                seen[s.ticker] = s
        return list(seen.values())

    def _extract_timeframes(
        self, market_data: pd.DataFrame | dict[str, pd.DataFrame]
    ) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
        if isinstance(market_data, dict):
            trend_df = market_data.get("trend")
            trigger_df = market_data.get("trigger")
            if trend_df is None or trigger_df is None:
                raise ValueError("Multi-timeframe veri 'trend' ve 'trigger' anahtarlarını içermeli")
            return trend_df, trigger_df, True
        return market_data, market_data, False

    def _get_trend_bias(self, df: pd.DataFrame) -> TrendBias:
        return get_trend_bias(self.indicators, df)

    def _apply_confluence(
        self, signal_type: SignalType, trend_bias: TrendBias, reasons: list[str]
    ) -> bool:
        return apply_confluence(signal_type, trend_bias, reasons)

    def _check_momentum_confirmation(self, df: pd.DataFrame, threshold: float = 4.0) -> bool:
        return check_momentum_confirmation(df, threshold)

    def _score_momentum(self, last, prev) -> tuple[float, list[str]]:
        return score_momentum(self.params, last, prev)

    def _score_trend(self, last, prev) -> tuple[float, list[str]]:
        return score_trend(self.params, last, prev)

    def _score_volume(self, last) -> tuple[float, list[str]]:
        return score_volume(self.params, last)

    def _score_structure(self, last) -> tuple[float, list[str]]:
        return score_structure(self.params, last)

    def _build_meta_features(
        self,
        last: pd.Series,
        *,
        score: float,
        trend_bias: TrendBias,
        risk_levels,
    ) -> dict[str, float]:
        ema_long = float(last.get(f"ema_{settings.EMA_LONG}", last.get("close", 0.0)) or 0.0)
        close_price = float(last.get("close", 0.0) or 0.0)
        return {
            "score": float(score),
            "adx": float(last.get("adx", 0.0) or 0.0),
            "rsi": float(last.get("rsi", 0.0) or 0.0),
            "volume_ratio": float(last.get("volume_ratio", 0.0) or 0.0),
            "atr_pct": float(risk_levels.atr_pct),
            "risk_reward_ratio": float(risk_levels.risk_reward_ratio),
            "volatility_scale": float(risk_levels.volatility_scale),
            "correlation_scale": float(risk_levels.correlation_scale),
            "trend_bias": float(trend_bias == TrendBias.LONG)
            - float(trend_bias == TrendBias.SHORT),
            "close_vs_ema_long": ((close_price / ema_long) - 1.0) if ema_long > 0 else 0.0,
        }

    def analyze(
        self,
        ticker: str,
        df: pd.DataFrame | dict[str, pd.DataFrame],
        enforce_sector_limit: bool = False,
    ) -> Signal | None:
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

        min_candles = getattr(self.params, "min_trigger_candles", 30)
        if trigger_df is None or len(trigger_df) < min_candles:
            logger.warning(
                f"  {ticker}: Yetersiz veri ({len(trigger_df) if trigger_df is not None else 0} mum)"
            )
            return None

        df = self.indicators.add_all(trigger_df.copy())
        trend_bias = (
            self._get_trend_bias(trend_df)
            if multi_timeframe and getattr(settings, "MTF_ENABLED", True)
            else TrendBias.NEUTRAL
        )

        last = df.iloc[-1].copy()
        prev = df.iloc[-2]
        last["_prev_close_for_scoring"] = prev["close"]
        score = 0.0
        reasons = []

        adx = last.get("adx")
        if not pd.notna(adx):
            logger.debug(f"  {ticker}: ADX hesaplanamadı (NaN) - sinyal üretme")
            return None
        adx_threshold = getattr(self.params, "adx_threshold", getattr(settings, "ADX_THRESHOLD", 20))
        if adx < adx_threshold:
            logger.debug(f"  {ticker}: ADX düşük ({adx:.1f}) - Trend yok, sinyal üretme")
            return None

        regime = detect_regime(df)
        if regime == MarketRegime.SIDEWAYS:
            reasons.append("Piyasa rejimi yatay - skor etkisi azaltıldı")

        s1, r1 = self._score_momentum(last, prev)
        s2, r2 = self._score_trend(last, prev)
        s3, r3 = self._score_volume(last)
        s4, r4 = self._score_structure(last)
        score = s1 + s2 + s3 + s4
        reasons = reasons + r1 + r2 + r3 + r4

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
            confidence = "confidence.high"
        elif score >= self.BUY_THRESHOLD:
            signal_type = SignalType.BUY
            confidence = "confidence.medium"
        elif score >= self.WEAK_BUY_THRESHOLD:
            signal_type = SignalType.WEAK_BUY
            confidence = "confidence.low"
        elif score <= self.STRONG_SELL_THRESHOLD:
            signal_type = SignalType.STRONG_SELL
            confidence = "confidence.high"
        elif score <= self.SELL_THRESHOLD:
            signal_type = SignalType.SELL
            confidence = "confidence.medium"
        elif score <= self.WEAK_SELL_THRESHOLD:
            signal_type = SignalType.WEAK_SELL
            confidence = "confidence.low"
        else:
            signal_type = SignalType.HOLD
            confidence = "confidence.low"

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
            if self.meta_model is not None and hasattr(self.meta_model, "predict_probability"):
                signal_probability = float(
                    self.meta_model.predict_probability(
                        self._build_meta_features(
                            last,
                            score=score,
                            trend_bias=trend_bias,
                            risk_levels=risk_levels,
                        )
                    )
                )
                risk_levels = self.risk_manager.apply_signal_probability(
                    df,
                    price,
                    risk_levels,
                    signal_probability,
                )
                if risk_levels.position_size <= 0:
                    logger.debug(f"  {ticker}: meta-model sizing nedeniyle sinyal atlandı")
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
            position_size=risk_levels.position_size,
            signal_probability=risk_levels.signal_probability,
            kelly_fraction=risk_levels.kelly_fraction,
            confidence=risk_levels.confidence
            if risk_levels.confidence != "confidence.low"
            else confidence,
        )

        signal.reasons.append(
            f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}"
        )
        signal.reasons.append(
            f"Pozisyon: {risk_levels.position_size} lot | Risk Bütçesi: ₺{risk_levels.risk_budget_tl:.2f}"
        )
        signal.reasons.append(
            f"Volatilite throttle: x{risk_levels.volatility_scale:.2f} | ATR%: %{risk_levels.atr_pct * 100:.2f}"
        )
        if risk_levels.signal_probability is not None:
            signal.reasons.append(
                f"Meta-model: P(up) %{risk_levels.signal_probability * 100:.1f} | Kelly %{risk_levels.kelly_fraction * 100:.2f}"
            )
        if risk_levels.liquidity_value > 0:
            signal.reasons.append(
                f"Likidite: ₺{risk_levels.liquidity_value:,.0f} ort. islem degeri"
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
        self, data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]]
    ) -> list[Signal]:
        """Analyze all fetched ticker data and return sorted signals.

        Args:
            data: Mapping of ticker symbols to price dataframes.

        Returns:
            Sorted list of generated signals.
        """
        signals = []
        self.risk_manager.reset_portfolio()
        self.risk_manager.build_global_correlation_cache(data)

        sector_scan = getattr(self.risk_manager, "sector_scan", None)
        if callable(sector_scan):
            with cast(AbstractContextManager[None], sector_scan()):
                for ticker, df in data.items():
                    signal = self.analyze(ticker, df, enforce_sector_limit=True)
                    if signal:
                        signals.append(signal)
        else:
            self.risk_manager.reset_sectors()
            for ticker, df in data.items():
                signal = self.analyze(ticker, df, enforce_sector_limit=True)
                if signal:
                    signals.append(signal)

        signals.sort(key=lambda s: s.score, reverse=True)

        return signals

    def get_actionable_signals(self, signals: list[Signal]) -> list[Signal]:
        """Filter out hold signals from the signal list.

        Args:
            signals: Full signal list.

        Returns:
            Only actionable signals.
        """
        return [s for s in signals if s.signal_type != SignalType.HOLD]
