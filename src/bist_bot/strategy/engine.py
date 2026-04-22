"""Signal scoring and classification logic for BIST trading ideas."""

from contextlib import AbstractContextManager
from typing import Any, Optional, cast

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.ml.features import build_feature_payload
from bist_bot.risk import RiskManager
from bist_bot.strategy.signal_models import Signal, SignalType
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

logger = get_logger(__name__, component="strategy")


class StrategyEngine:
    def __init__(
        self,
        indicators: Optional[TechnicalIndicators] = None,
        risk_manager: Optional[RiskManager] = None,
        params: Optional[StrategyParams] = None,
        meta_model: Any | None = None,
    ) -> None:
        """Initialize injectable indicator and risk-management dependencies."""
        self.indicators = indicators or TechnicalIndicators()
        self.risk_manager = risk_manager or RiskManager(
            capital=getattr(settings, "INITIAL_CAPITAL", 8500.0)
        )
        self.params = params or StrategyParams()
        self.meta_model = meta_model
        self.STRONG_BUY_THRESHOLD = self.params.strong_buy_threshold
        self.BUY_THRESHOLD = self.params.buy_threshold
        self.WEAK_BUY_THRESHOLD = self.params.weak_buy_threshold
        self.WEAK_SELL_THRESHOLD = self.params.weak_sell_threshold
        self.SELL_THRESHOLD = self.params.sell_threshold
        self.STRONG_SELL_THRESHOLD = self.params.strong_sell_threshold
        self.SIDEWAYS_EXTRA_THRESHOLD = self.params.sideways_extra_threshold
        self.MOMENTUM_CONFIRMATION = self.params.momentum_confirmation_threshold

    def _extract_timeframes(
        self, market_data: pd.DataFrame | dict[str, pd.DataFrame]
    ) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
        if isinstance(market_data, dict):
            trend_df = market_data.get("trend")
            trigger_df = market_data.get("trigger")
            if trend_df is None or trigger_df is None:
                raise ValueError(
                    "Multi-timeframe veri 'trend' ve 'trigger' anahtarlarını içermeli"
                )
            return trend_df, trigger_df, True
        return market_data, market_data, False

    def _get_trend_bias(self, df: pd.DataFrame) -> TrendBias:
        return get_trend_bias(self.indicators, df)

    def _apply_confluence(
        self, signal_type: SignalType, trend_bias: TrendBias, reasons: list[str]
    ) -> bool:
        return apply_confluence(signal_type, trend_bias, reasons)

    def _check_momentum_confirmation(
        self, df: pd.DataFrame, threshold: float = 4.0
    ) -> bool:
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
        return build_feature_payload(
            last,
            score=score,
            stop_loss=float(risk_levels.final_stop),
            target_price=float(risk_levels.final_target),
            volatility_scale=float(risk_levels.volatility_scale),
            correlation_scale=float(risk_levels.correlation_scale),
            trend_bias=float(trend_bias == TrendBias.LONG)
            - float(trend_bias == TrendBias.SHORT),
        )

    def _has_enough_trigger_data(self, ticker: str, trigger_df: pd.DataFrame) -> bool:
        if len(trigger_df) >= 30:
            return True
        logger.warning(
            "strategy_insufficient_data",
            ticker=ticker,
            candle_count=len(trigger_df),
        )
        return False

    def _prepare_analysis_frame(
        self,
        trigger_df: pd.DataFrame,
        *,
        trend_df: pd.DataFrame,
        multi_timeframe: bool,
    ) -> tuple[pd.DataFrame, TrendBias, pd.Series, pd.Series]:
        analysis_df = self.indicators.add_all(trigger_df.copy())
        trend_bias = (
            self._get_trend_bias(trend_df)
            if multi_timeframe and getattr(settings, "MTF_ENABLED", True)
            else TrendBias.NEUTRAL
        )
        last = analysis_df.iloc[-1].copy()
        prev = analysis_df.iloc[-2]
        last["_prev_close_for_scoring"] = prev["close"]
        return analysis_df, trend_bias, last, prev

    def _passes_adx_filter(self, ticker: str, last: pd.Series) -> bool:
        adx_raw = last.get("adx")
        if pd.isna(adx_raw):
            return True
        adx = float(adx_raw)
        if adx >= getattr(settings, "ADX_THRESHOLD", 20):
            return True
        logger.debug("strategy_adx_filtered", ticker=ticker, adx=round(float(adx), 2))
        return False

    def _calculate_score_and_reasons(
        self,
        ticker: str,
        df: pd.DataFrame,
        *,
        last: pd.Series,
        prev: pd.Series,
    ) -> tuple[float, list[str]] | None:
        reasons: list[str] = []
        regime = detect_regime(df)
        if regime == MarketRegime.SIDEWAYS:
            reasons.append("Piyasa rejimi yatay - skor etkisi azaltıldı")

        s1, r1 = self._score_momentum(last, prev)
        s2, r2 = self._score_trend(last, prev)
        s3, r3 = self._score_volume(last)
        s4, r4 = self._score_structure(last)
        score = s1 + s2 + s3 + s4
        reasons.extend(r1 + r2 + r3 + r4)

        if regime == MarketRegime.SIDEWAYS:
            score *= 0.6
            if abs(score) < self.BUY_THRESHOLD:
                logger.debug(
                    "strategy_sideways_filtered",
                    ticker=ticker,
                    score=round(float(score), 2),
                )
                return None

        if score > 0 and not self._check_momentum_confirmation(
            df, self.MOMENTUM_CONFIRMATION
        ):
            if abs(score) < self.BUY_THRESHOLD + self.SIDEWAYS_EXTRA_THRESHOLD:
                logger.debug(
                    "strategy_momentum_filtered",
                    ticker=ticker,
                    score=round(float(score), 2),
                )
                return None

        score = max(-100, min(100, score))
        if score == 0:
            return None
        return score, reasons

    def _classify_signal(self, score: float) -> tuple[SignalType, str]:
        if score >= self.STRONG_BUY_THRESHOLD:
            return SignalType.STRONG_BUY, "confidence.high"
        if score >= self.BUY_THRESHOLD:
            return SignalType.BUY, "confidence.medium"
        if score >= self.WEAK_BUY_THRESHOLD:
            return SignalType.WEAK_BUY, "confidence.low"
        if score <= self.STRONG_SELL_THRESHOLD:
            return SignalType.STRONG_SELL, "confidence.high"
        if score <= self.SELL_THRESHOLD:
            return SignalType.SELL, "confidence.medium"
        if score <= self.WEAK_SELL_THRESHOLD:
            return SignalType.WEAK_SELL, "confidence.low"
        return SignalType.HOLD, "confidence.low"

    def _is_buy_signal(self, signal_type: SignalType) -> bool:
        return signal_type in {
            SignalType.STRONG_BUY,
            SignalType.BUY,
            SignalType.WEAK_BUY,
        }

    def _apply_buy_side_risk(
        self,
        ticker: str,
        df: pd.DataFrame,
        *,
        signal_type: SignalType,
        enforce_sector_limit: bool,
        last: pd.Series,
        score: float,
        trend_bias: TrendBias,
        risk_levels: Any,
    ) -> Any | None:
        if not self._is_buy_signal(signal_type):
            return risk_levels
        if enforce_sector_limit and not self.risk_manager.check_sector_limit(ticker):
            logger.debug("strategy_sector_filtered", ticker=ticker)
            return None

        price = float(last["close"])
        risk_levels = self.risk_manager.apply_portfolio_risk(ticker, df, risk_levels)
        if risk_levels.blocked_by_correlation or risk_levels.position_size <= 0:
            logger.debug("strategy_portfolio_risk_filtered", ticker=ticker)
            return None

        if self.meta_model is not None and hasattr(
            self.meta_model, "predict_probability"
        ):
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
                logger.debug("strategy_meta_model_filtered", ticker=ticker)
                return None
        return risk_levels

    def _build_signal(
        self,
        ticker: str,
        *,
        signal_type: SignalType,
        score: float,
        last: pd.Series,
        reasons: list[str],
        risk_levels: Any,
        fallback_confidence: str,
    ) -> Signal:
        return Signal(
            ticker=ticker,
            signal_type=signal_type,
            score=score,
            price=float(last["close"]),
            reasons=reasons,
            stop_loss=round(risk_levels.final_stop, 2),
            target_price=round(risk_levels.final_target, 2),
            position_size=risk_levels.position_size,
            signal_probability=risk_levels.signal_probability,
            kelly_fraction=risk_levels.kelly_fraction,
            confidence=(
                risk_levels.confidence
                if risk_levels.confidence != "confidence.low"
                else fallback_confidence
            ),
        )

    def _append_signal_reasons(self, signal: Signal, risk_levels: Any) -> None:
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

    def _passes_multi_timeframe_confluence(
        self,
        ticker: str,
        *,
        signal: Signal,
        trend_bias: TrendBias,
        multi_timeframe: bool,
    ) -> bool:
        if not (multi_timeframe and getattr(settings, "MTF_ENABLED", True)):
            return True
        if self._apply_confluence(signal.signal_type, trend_bias, signal.reasons):
            return True
        logger.debug("strategy_mtf_filtered", ticker=ticker)
        return False

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
        if not self._has_enough_trigger_data(ticker, trigger_df):
            return None

        df, trend_bias, last, prev = self._prepare_analysis_frame(
            trigger_df,
            trend_df=trend_df,
            multi_timeframe=multi_timeframe,
        )
        if not self._passes_adx_filter(ticker, last):
            return None
        scored = self._calculate_score_and_reasons(ticker, df, last=last, prev=prev)
        if scored is None:
            return None
        score, reasons = scored
        signal_type, confidence = self._classify_signal(score)
        risk_levels = self.risk_manager.calculate(df)
        risk_levels = self._apply_buy_side_risk(
            ticker,
            df,
            signal_type=signal_type,
            enforce_sector_limit=enforce_sector_limit,
            last=last,
            score=score,
            trend_bias=trend_bias,
            risk_levels=risk_levels,
        )
        if risk_levels is None:
            return None
        signal = self._build_signal(
            ticker,
            signal_type=signal_type,
            score=score,
            last=last,
            reasons=reasons,
            risk_levels=risk_levels,
            fallback_confidence=confidence,
        )
        self._append_signal_reasons(signal, risk_levels)
        if not self._passes_multi_timeframe_confluence(
            ticker,
            signal=signal,
            trend_bias=trend_bias,
            multi_timeframe=multi_timeframe,
        ):
            return None
        if self._is_buy_signal(signal_type):
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
