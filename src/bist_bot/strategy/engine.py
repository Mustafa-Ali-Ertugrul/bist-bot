"""Signal scoring and classification orchestration for BIST trading ideas."""

from contextlib import AbstractContextManager
from typing import Any, Optional, cast

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.risk import RiskLevels, RiskManager
from bist_bot.strategy.engine_core import extract_timeframes, prepare_analysis_frame
from bist_bot.strategy.engine_filters import (
    calculate_score_and_reasons,
    classify_signal,
    is_buy_signal,
    passes_adx_filter,
    passes_multi_timeframe_confluence,
)
from bist_bot.strategy.engine_meta import (
    append_signal_reasons,
    apply_buy_side_risk,
    build_meta_features,
)
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import (
    TrendBias,
    apply_confluence,
    check_momentum_confirmation,
    get_trend_bias,
)
from bist_bot.strategy.scoring import (
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)
from bist_bot.strategy.signal_models import Signal, SignalType

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
        return extract_timeframes(market_data)

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

    def _score_momentum(self, last: pd.Series, prev: pd.Series) -> tuple[float, list[str]]:
        return score_momentum(self.params, last, prev)

    def _score_trend(self, last: pd.Series, prev: pd.Series) -> tuple[float, list[str]]:
        return score_trend(self.params, last, prev)

    def _score_volume(self, last: pd.Series) -> tuple[float, list[str]]:
        return score_volume(self.params, last)

    def _score_structure(self, last: pd.Series) -> tuple[float, list[str]]:
        return score_structure(self.params, last)

    def _build_meta_features(
        self,
        last: pd.Series,
        *,
        score: float,
        trend_bias: TrendBias,
        risk_levels: RiskLevels,
    ) -> dict[str, float]:
        return build_meta_features(
            last,
            score=score,
            trend_bias=trend_bias,
            risk_levels=risk_levels,
        )

    def _has_enough_trigger_data(self, ticker: str, trigger_df: pd.DataFrame) -> bool:
        if len(trigger_df) >= self.params.min_trigger_candles:
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
        if multi_timeframe and getattr(settings, "MTF_ENABLED", True):
            analysis_df = self.indicators.add_all(trigger_df.copy())
            trend_bias = self._get_trend_bias(trend_df)
            last = analysis_df.iloc[-1].copy()
            prev = analysis_df.iloc[-2]
            last["_prev_close_for_scoring"] = prev["close"]
            return analysis_df, trend_bias, last, prev
        return prepare_analysis_frame(
            self.indicators,
            trigger_df,
            trend_df=trend_df,
            multi_timeframe=multi_timeframe,
        )

    def _passes_adx_filter(self, ticker: str, last: pd.Series) -> bool:
        return passes_adx_filter(self.params, ticker, last)

    def _calculate_score_and_reasons(
        self,
        ticker: str,
        df: pd.DataFrame,
        *,
        last: pd.Series,
        prev: pd.Series,
    ) -> tuple[float, list[str]] | None:
        return calculate_score_and_reasons(
            self.params,
            ticker,
            df,
            last=last,
            prev=prev,
            momentum_scorer=self._score_momentum,
            trend_scorer=self._score_trend,
            volume_scorer=self._score_volume,
            structure_scorer=self._score_structure,
            momentum_checker=self._check_momentum_confirmation,
        )

    def _classify_signal(self, score: float) -> tuple[SignalType, str]:
        return classify_signal(self.params, score)

    def _is_buy_signal(self, signal_type: SignalType) -> bool:
        return is_buy_signal(signal_type)

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
        risk_levels: RiskLevels,
    ) -> RiskLevels | None:
        return apply_buy_side_risk(
            self.risk_manager,
            self.meta_model,
            ticker,
            df,
            signal_type=signal_type,
            enforce_sector_limit=enforce_sector_limit,
            last=last,
            score=score,
            trend_bias=trend_bias,
            risk_levels=risk_levels,
        )

    def _build_signal(
        self,
        ticker: str,
        *,
        signal_type: SignalType,
        score: float,
        last: pd.Series,
        reasons: list[str],
        risk_levels: RiskLevels,
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

    def _append_signal_reasons(self, signal: Signal, risk_levels: RiskLevels) -> None:
        append_signal_reasons(signal, risk_levels)

    def _passes_multi_timeframe_confluence(
        self,
        ticker: str,
        *,
        signal: Signal,
        trend_bias: TrendBias,
        multi_timeframe: bool,
    ) -> bool:
        return passes_multi_timeframe_confluence(
            ticker,
            signal=signal,
            trend_bias=trend_bias,
            multi_timeframe=multi_timeframe,
            confluence_applier=self._apply_confluence,
        )

    def analyze(
        self,
        ticker: str,
        df: pd.DataFrame | dict[str, pd.DataFrame],
        enforce_sector_limit: bool = False,
    ) -> Optional[Signal]:
        """Score a ticker and build a signal when thresholds are met."""
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
        adjusted_risk_levels = self._apply_buy_side_risk(
            ticker,
            df,
            signal_type=signal_type,
            enforce_sector_limit=enforce_sector_limit,
            last=last,
            score=score,
            trend_bias=trend_bias,
            risk_levels=risk_levels,
        )
        if adjusted_risk_levels is None:
            return None
        risk_levels = adjusted_risk_levels
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
        """Analyze all fetched ticker data and return sorted signals."""
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
        """Filter out hold signals from the signal list."""
        return [s for s in signals if s.signal_type != SignalType.HOLD]
