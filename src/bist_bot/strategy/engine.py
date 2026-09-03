"""Signal scoring and classification orchestration for BIST trading ideas."""

from contextlib import AbstractContextManager
from typing import Any, cast
from uuid import uuid4

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.risk import RiskLevels, RiskManager
from bist_bot.strategy.base import BaseStrategy
from bist_bot.strategy.engine_core import extract_timeframes, prepare_analysis_frame
from bist_bot.strategy.engine_filters import (
    apply_low_adx_penalty,
    calculate_score_and_reasons,
    classify_signal,
    get_valid_adx,
    is_buy_signal,
    passes_adx_filter,
)
from bist_bot.strategy.engine_filters import (
    is_trade_actionable as signal_is_trade_actionable,
)
from bist_bot.strategy.engine_meta import (
    append_signal_reasons,
    apply_buy_side_risk,
    build_meta_features,
)
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import (
    MACRO_BENCHMARK_TICKERS,
    MarketRegime,
    TrendBias,
    apply_confluence,
    check_momentum_confirmation,
    detect_macro_regime,
    get_trend_bias,
)
from bist_bot.strategy.scoring import (
    _compute_ema_slope,
    combine_component_scores,
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)
from bist_bot.strategy.signal_models import Signal, SignalType

logger = get_logger(__name__, component="strategy")


def _empty_rejection_breakdown(scan_id: str = "") -> dict[str, object]:
    return {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": scan_id,
    }


def _summary_entry(rows: object, key: str) -> tuple[str, int]:
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        first = rows[0]
        value = str(first.get(key, "") or "")
        raw_count = first.get("count", 0)
        count = int(raw_count) if isinstance(raw_count, int | float | str) else 0
        return value, count
    return "", 0


def _coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


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
            capital=getattr(settings, "INITIAL_CAPITAL", 8500.0)
        )
        self.params = params or StrategyParams.from_settings()
        self.meta_model = meta_model
        self.STRONG_BUY_THRESHOLD = self.params.strong_buy_threshold
        self.BUY_THRESHOLD = self.params.buy_threshold
        self.WEAK_BUY_THRESHOLD = self.params.weak_buy_threshold
        self.WEAK_SELL_THRESHOLD = self.params.weak_sell_threshold
        self.SELL_THRESHOLD = self.params.sell_threshold
        self.STRONG_SELL_THRESHOLD = self.params.strong_sell_threshold
        self.SIDEWAYS_EXTRA_THRESHOLD = self.params.sideways_extra_threshold
        self.MOMENTUM_CONFIRMATION = self.params.momentum_confirmation_threshold
        # Plugin registry — external strategies can be added at runtime
        self._strategies: list[BaseStrategy] = []
        self._current_scan_id: str | None = None
        self._current_rejection_counts: dict[str, dict[str, int]] = {"reason": {}, "stage": {}}
        self._last_rejection_breakdown: dict[str, object] = _empty_rejection_breakdown()
        self.last_macro_regime: MarketRegime = MarketRegime.UNKNOWN

    def _reset_rejection_aggregation(self) -> None:
        self._current_rejection_counts = {"reason": {}, "stage": {}}

    def _finalize_rejection_breakdown(self, scan_id: str) -> None:
        by_reason_items = sorted(
            self._current_rejection_counts["reason"].items(),
            key=lambda item: (-item[1], item[0]),
        )
        by_stage_items = sorted(
            self._current_rejection_counts["stage"].items(),
            key=lambda item: (-item[1], item[0]),
        )
        by_reason = [
            {"reason_code": reason_code, "count": count} for reason_code, count in by_reason_items
        ]
        by_stage = [{"stage": stage, "count": count} for stage, count in by_stage_items]
        total_rejections = sum(count for _, count in by_reason_items)
        self._last_rejection_breakdown = {
            "total_rejections": total_rejections,
            "by_reason": by_reason,
            "by_stage": by_stage,
            "scan_id": scan_id,
        }
        top_reason, top_reason_count = _summary_entry(by_reason, "reason_code")
        top_stage, top_stage_count = _summary_entry(by_stage, "stage")
        logger.info(
            "scan_rejection_summary",
            scan_id=scan_id,
            total_rejections=total_rejections,
            top_reason=top_reason,
            top_reason_count=top_reason_count,
            top_stage=top_stage,
            top_stage_count=top_stage_count,
        )

    def get_last_rejection_breakdown(self) -> dict[str, object]:
        by_reason = cast(
            list[dict[str, object]], self._last_rejection_breakdown.get("by_reason", [])
        )
        by_stage = cast(list[dict[str, object]], self._last_rejection_breakdown.get("by_stage", []))
        return {
            "total_rejections": _coerce_int(
                self._last_rejection_breakdown.get("total_rejections", 0)
            ),
            "by_reason": list(by_reason),
            "by_stage": list(by_stage),
            "scan_id": str(self._last_rejection_breakdown.get("scan_id", "") or ""),
        }

    def _resolve_scan_id(self) -> str:
        return self._current_scan_id or f"manual-{uuid4().hex[:12]}"

    def _timeframe_label(self, multi_timeframe: bool) -> str:
        if multi_timeframe and getattr(settings, "MTF_ENABLED", True):
            return f"trigger:{settings.MTF_TRIGGER_INTERVAL}|trend:{settings.MTF_TREND_INTERVAL}"
        return str(getattr(settings, "DATA_INTERVAL", "1d"))

    def _log_candidate_rejected(
        self,
        ticker: str,
        *,
        stage: str,
        reason_code: str,
        multi_timeframe: bool,
        trigger_candle_count: int,
        score: float | None = None,
        signal_type: str | None = None,
        trend_bias: str | None = None,
        adx: float | None = None,
        position_size: int | None = None,
        blocked_by_correlation: bool | None = None,
        liquidity_value: float | None = None,
        signal_probability: float | None = None,
        reason_detail: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "ticker": ticker,
            "stage": stage,
            "reason_code": reason_code,
            "scan_id": self._resolve_scan_id(),
            "timeframe": self._timeframe_label(multi_timeframe),
            "multi_timeframe": multi_timeframe,
            "trigger_candle_count": trigger_candle_count,
        }
        if score is not None:
            payload["score"] = round(float(score), 2)
        if signal_type is not None:
            payload["signal_type"] = signal_type
        if trend_bias is not None:
            payload["trend_bias"] = trend_bias
        if adx is not None:
            payload["adx"] = round(float(adx), 2)
        if position_size is not None:
            payload["position_size"] = int(position_size)
        if blocked_by_correlation is not None:
            payload["blocked_by_correlation"] = blocked_by_correlation
        if liquidity_value is not None:
            payload["liquidity_value"] = round(float(liquidity_value), 2)
        if signal_probability is not None:
            payload["signal_probability"] = round(float(signal_probability), 4)
        if reason_detail is not None:
            payload["reason_detail"] = reason_detail
        self._current_rejection_counts["reason"][reason_code] = (
            self._current_rejection_counts["reason"].get(reason_code, 0) + 1
        )
        self._current_rejection_counts["stage"][stage] = (
            self._current_rejection_counts["stage"].get(stage, 0) + 1
        )
        logger.info("strategy_candidate_rejected", **payload)

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

    def _check_momentum_confirmation(self, df: pd.DataFrame, threshold: float = 4.0) -> bool:
        return check_momentum_confirmation(df, threshold)

    def _score_momentum(self, last: pd.Series, prev: pd.Series) -> tuple[float, list[str]]:
        return score_momentum(self.params, last, prev)

    def _score_trend(
        self, last: pd.Series, prev: pd.Series, df: pd.DataFrame | None = None
    ) -> tuple[float, list[str]]:
        return score_trend(self.params, last, prev, df)

    def _score_volume(self, last: pd.Series, prev: pd.Series) -> tuple[float, list[str]]:
        return score_volume(self.params, last, prev)

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
        multi_timeframe: bool,
    ) -> tuple[float, list[str], float | None] | None:
        result = calculate_score_and_reasons(
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
            reject_logger=lambda **fields: self._log_candidate_rejected(
                ticker,
                multi_timeframe=multi_timeframe,
                trigger_candle_count=len(df),
                **fields,
            ),
        )
        return result

    def _build_score_breakdown(
        self,
        last: pd.Series,
        prev: pd.Series,
        df: pd.DataFrame | None = None,
        *,
        final_score: float | None = None,
    ) -> dict[str, float]:
        """Compute a per-component score breakdown for explainability.

        Legacy mode returns the four raw component values (momentum / trend /
        volume / structure). In research/normalized mode the breakdown shows
        the effective weighted contributions and, when ``final_score`` is
        provided, an ``adjustments`` entry so the rounded breakdown sums to
        the final score after later filters/caps/low-ADX penalty.
        """
        s_momentum, _ = self._score_momentum(last, prev)
        s_trend, _ = self._score_trend(last, prev, df)
        s_volume, _ = self._score_volume(last, prev)
        s_structure, _ = self._score_structure(last)

        if not getattr(self.params, "normalized_component_scoring", False):
            return {
                "momentum": round(float(s_momentum), 2),
                "trend": round(float(s_trend), 2),
                "volume": round(float(s_volume), 2),
                "structure": round(float(s_structure), 2),
            }

        _, contributions = combine_component_scores(
            self.params, s_momentum, s_trend, s_volume, s_structure
        )
        breakdown = {k: round(float(v), 2) for k, v in contributions.items()}
        if final_score is not None:
            adjustment = round(float(final_score) - sum(breakdown.values()), 2)
            if adjustment != 0.0:
                breakdown["adjustments"] = adjustment
        return breakdown

    def _classify_signal(
        self, score: float, agreement_ratio: float | None = None
    ) -> tuple[SignalType, str]:
        return classify_signal(self.params, score, agreement_ratio)

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
        multi_timeframe: bool,
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
            reject_logger=lambda **fields: self._log_candidate_rejected(
                ticker,
                multi_timeframe=multi_timeframe,
                trigger_candle_count=len(df),
                trend_bias=trend_bias.value,
                **fields,
            ),
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
        agreement_ratio: float | None = None,
        score_breakdown: dict[str, float] | None = None,
        trigger_df: pd.DataFrame | None = None,
    ) -> Signal:
        signal = Signal(
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
            confidence=fallback_confidence,
            agreement_ratio=agreement_ratio,
            buy_threshold=self.params.buy_threshold,
            sell_threshold=self.params.sell_threshold,
            score_breakdown=score_breakdown,
            ema_200=float(last.get(f"ema_{settings.EMA_LONG}", last.get("ema_200")) or 0.0),
            ema_200_slope=self._get_ema200_slope(trigger_df),
        )
        # Single source of actionable truth: engine computes, downstream reads.
        signal.is_actionable = signal_is_trade_actionable(signal, self.params)
        return signal

    def _get_ema200_slope(self, df: pd.DataFrame | None) -> float | None:
        """Return EMA200 direction: >0 rising, <0 falling, None if insufficient data."""
        if df is None or len(df) < 41:
            return None
        slope = _compute_ema_slope(df, 40)
        return float(slope) if slope is not None else None

    def _append_signal_reasons(self, signal: Signal, risk_levels: RiskLevels) -> None:
        append_signal_reasons(signal, risk_levels)

    def _evaluate_confluence(
        self,
        ticker: str,
        *,
        signal: Signal,
        trend_bias: TrendBias,
        multi_timeframe: bool,
        trigger_candle_count: int,
    ) -> SignalType:
        """Evaluate signal confluence and determine if it should be upgraded to RADAR or rejected."""
        if not (multi_timeframe and getattr(settings, "MTF_ENABLED", True)):
            return signal.signal_type

        # Use our enhanced apply_confluence which now adds specific reasons
        if self._apply_confluence(signal.signal_type, trend_bias, signal.reasons):
            return signal.signal_type

        # Logic Tuning Phase 4A: Check for RADAR (watchlist) eligibility
        # If bias is neutral (soft fail) but score is positive and strong, keep as RADAR.
        # Negative (short/sell) candidates that fail confluence must be rejected as HOLD, not RADAR.
        if trend_bias == TrendBias.NEUTRAL:
            if signal.score >= self.BUY_THRESHOLD:
                logger.debug(
                    "strategy_confluence_soft_fail_radar", ticker=ticker, score=signal.score
                )
                return SignalType.RADAR
            if signal.score < 0:
                self._log_candidate_rejected(
                    ticker,
                    stage="confluence",
                    reason_code="confluence_soft_fail_short",
                    multi_timeframe=multi_timeframe,
                    trigger_candle_count=trigger_candle_count,
                    trend_bias=trend_bias.value,
                    score=signal.score,
                    reason_detail="short candidate with neutral HTF bias soft-failed to HOLD",
                )
                return SignalType.HOLD

        self._log_candidate_rejected(
            ticker,
            stage="confluence",
            reason_code="confluence_failed",
            multi_timeframe=multi_timeframe,
            trigger_candle_count=trigger_candle_count,
            trend_bias=trend_bias.value,
            score=signal.score,
            reason_detail=f"signal {signal.signal_type.name} mismatch with HTF bias {trend_bias.value}",
        )
        return SignalType.HOLD

    def analyze(
        self,
        ticker: str,
        df: pd.DataFrame | dict[str, pd.DataFrame],
        enforce_sector_limit: bool = False,
    ) -> Signal | None:
        """Score a ticker and build a signal when thresholds are met."""
        trend_df, trigger_df, multi_timeframe = self._extract_timeframes(df)
        if not self._has_enough_trigger_data(ticker, trigger_df):
            self._log_candidate_rejected(
                ticker,
                stage="data",
                reason_code="insufficient_history",
                multi_timeframe=multi_timeframe,
                trigger_candle_count=len(trigger_df),
                reason_detail="trigger candle count below minimum requirement",
            )
            return None

        df, trend_bias, last, prev = self._prepare_analysis_frame(
            trigger_df,
            trend_df=trend_df,
            multi_timeframe=multi_timeframe,
        )
        if not self._passes_adx_filter(ticker, last):
            self._log_candidate_rejected(
                ticker,
                stage="indicators",
                reason_code="adx_missing",
                multi_timeframe=multi_timeframe,
                trigger_candle_count=len(df),
                reason_detail="adx missing or non-numeric on latest candle",
            )
            return None

        adx = get_valid_adx(self.params, ticker, last)
        _score_result = self._calculate_score_and_reasons(
            ticker,
            df,
            last=last,
            prev=prev,
            multi_timeframe=multi_timeframe,
        )
        if _score_result is None:
            return None

        score, reasons, _agreement = _score_result
        if adx is not None and adx < self.params.adx_threshold:
            score, reasons = apply_low_adx_penalty(self.params, adx, score, reasons)
            if score == 0:
                self._log_candidate_rejected(
                    ticker,
                    stage="scoring",
                    reason_code="score_zero_after_penalty",
                    multi_timeframe=multi_timeframe,
                    trigger_candle_count=len(df),
                    score=score,
                    adx=adx,
                    reason_detail="low adx penalty neutralized candidate score",
                )
                return None

        # Capture per-component breakdown once scoring is finalized.
        score_breakdown = self._build_score_breakdown(last, prev, df, final_score=score)

        signal_type, confidence = self._classify_signal(score, _agreement)
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
            multi_timeframe=multi_timeframe,
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
            agreement_ratio=_agreement,
            score_breakdown=score_breakdown,
            trigger_df=df,
        )
        self._append_signal_reasons(signal, risk_levels)

        # Apply confluence evaluation (may downgrade to RADAR or HOLD)
        final_signal_type = self._evaluate_confluence(
            ticker,
            signal=signal,
            trend_bias=trend_bias,
            multi_timeframe=multi_timeframe,
            trigger_candle_count=len(df),
        )

        if final_signal_type == SignalType.HOLD:
            if signal.signal_type != SignalType.HOLD:
                # Confluence already logged a rejection for this ticker
                pass
            else:
                # Score fell in neutral zone — not rejected by any filter
                # but also not actionable. Log so the count is complete.
                self._log_candidate_rejected(
                    ticker,
                    stage="classification",
                    reason_code="hold_neutral_zone",
                    multi_timeframe=multi_timeframe,
                    trigger_candle_count=len(df),
                    score=score,
                    reason_detail="score in neutral zone, signal classified as HOLD",
                )
            return None

        signal.signal_type = final_signal_type
        signal.is_actionable = signal_is_trade_actionable(signal, self.params)
        if self._is_buy_signal(signal.signal_type):
            self.risk_manager.register_position(ticker, df)
        return signal

    def _detect_macro_regime(
        self, data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]]
    ) -> MarketRegime:
        """Aggregate per-benchmark regimes from trend frames present in the scan.

        Benchmark trend frames are enriched with indicators and fed to
        ``detect_macro_regime``. Missing or too-short benchmark data degrades
        gracefully to ``UNKNOWN`` (no gate applied).
        """
        benchmark_dfs: dict[str, pd.DataFrame] = {}
        for ticker in MACRO_BENCHMARK_TICKERS:
            ticker_data = data.get(ticker)
            if ticker_data is None:
                continue
            trend_df = (
                ticker_data.get("trend", ticker_data)
                if isinstance(ticker_data, dict)
                else ticker_data
            )
            if trend_df is None or len(trend_df) < 50:
                continue
            try:
                benchmark_dfs[ticker] = self.indicators.add_all(trend_df.copy())
            except Exception as exc:
                logger.debug(
                    "macro_regime_enrichment_failed",
                    ticker=ticker,
                    error_type=type(exc).__name__,
                )
        return detect_macro_regime(benchmark_dfs)

    def _apply_macro_regime_gate(
        self,
        signals: list[Signal],
        data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]],
    ) -> None:
        """Demote buy-family signals to RADAR when the macro regime is BEAR.

        Opening new long positions against a bearish macro backdrop is blocked;
        sell/exit signals stay untouched so open positions can still be closed.
        The gate is a no-op when disabled, when benchmark data is unavailable,
        or when the regime is not BEAR.
        """
        if not getattr(settings, "MACRO_REGIME_GATE_ENABLED", True):
            return
        self.last_macro_regime = self._detect_macro_regime(data)
        if self.last_macro_regime != MarketRegime.BEAR:
            return
        buy_family = {
            SignalType.STRONG_BUY,
            SignalType.BUY,
            SignalType.WEAK_BUY,
        }
        demoted = 0
        for signal in signals:
            if signal.signal_type in buy_family:
                signal.signal_type = SignalType.RADAR
                signal.is_actionable = signal_is_trade_actionable(signal, self.params)
                signal.reasons.append("Makro rejim BEAR → alım sinyali RADAR'a düşürüldü")
                demoted += 1
        if demoted:
            logger.warning(
                "macro_regime_gate_demoted",
                demoted=demoted,
                macro_regime=str(self.last_macro_regime.value),
            )

    def scan_all(
        self, data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]]
    ) -> list[Signal]:
        """Analyze all fetched ticker data and return sorted signals."""
        signals = []
        self._current_scan_id = f"scan-{uuid4().hex[:12]}"
        self._reset_rejection_aggregation()
        try:
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
            self._apply_macro_regime_gate(signals, data)
        finally:
            self._finalize_rejection_breakdown(self._current_scan_id or "")
            self._current_scan_id = None
        return signals

    def is_trade_actionable(self, signal: Signal) -> bool:
        """Check whether `signal` crosses the directional trade thresholds.

        Delegates to :func:`engine_filters.is_trade_actionable` using this
        engine's params — the single actionable contract for scanner,
        paper-trade, metrics, and notification layers.
        """
        return signal_is_trade_actionable(signal, self.params)

    def get_actionable_signals(self, signals: list[Signal]) -> list[Signal]:
        """Return only signals intended for immediate trade execution.

        Actionable = directional threshold cross (buy: score >= buy_threshold,
        sell: score <= sell_threshold). HOLD/RADAR and weak sub-threshold
        signals are observation-only (handled by the shadow ledger).
        """
        return [s for s in signals if self.is_trade_actionable(s)]

    # ------------------------------------------------------------------
    # Plugin registry API
    # ------------------------------------------------------------------

    def register_strategy(self, strategy: BaseStrategy) -> None:
        """Register an external strategy plugin.

        The strategy will be invoked alongside the built-in engine logic when
        ``scan_with_plugins`` is called.

        Args:
            strategy: Any object implementing ``BaseStrategy``.
        """
        self._strategies.append(strategy)
        logger.info("strategy_registered", strategy_name=strategy.name)

    def unregister_strategy(self, name: str) -> bool:
        """Remove a registered strategy by name.

        Args:
            name: The ``strategy.name`` to remove.

        Returns:
            True if the strategy was found and removed, False otherwise.
        """
        before = len(self._strategies)
        self._strategies = [s for s in self._strategies if s.name != name]
        removed = len(self._strategies) < before
        if removed:
            logger.info("strategy_unregistered", strategy_name=name)
        return removed

    def scan_with_plugins(
        self,
        data: dict[str, pd.DataFrame] | dict[str, dict[str, pd.DataFrame]],
    ) -> list[Signal]:
        """Run all registered plugin strategies against the full dataset.

        Falls back to the built-in ``scan_all`` when no plugins are registered.
        Plugin signals are merged with built-in signals and de-duplicated by
        (ticker, signal_type) keeping the highest-score entry.

        Args:
            data: Mapping of ticker → OHLCV DataFrame (or multi-timeframe dict).

        Returns:
            Deduplicated, sorted list of signals from all strategies.
        """
        # Always run the built-in engine first.
        builtin_signals = self.scan_all(data)

        if not self._strategies:
            return builtin_signals

        plugin_signals: list[Signal] = []
        for ticker, df in data.items():
            for strategy in self._strategies:
                try:
                    sig = strategy.analyze(ticker, df)
                    if sig is not None:
                        plugin_signals.append(sig)
                        logger.info(
                            "plugin_signal_generated",
                            strategy=strategy.name,
                            ticker=ticker,
                            score=sig.score,
                        )
                except Exception as exc:
                    logger.error(
                        "plugin_strategy_error",
                        strategy=strategy.name,
                        ticker=ticker,
                        error_type=type(exc).__name__,
                    )

        # Merge: prefer stronger score per (ticker, signal_type)
        # For sell signals, more negative is stronger; for others, more positive is stronger.
        all_signals = builtin_signals + plugin_signals
        seen: dict[tuple[str, str], Signal] = {}
        for sig in all_signals:
            key = (sig.ticker, sig.signal_type.name)
            if key not in seen:
                seen[key] = sig
            else:
                existing = seen[key]
                if sig.signal_type.is_sell:
                    if sig.score < existing.score:
                        seen[key] = sig
                else:
                    if sig.score > existing.score:
                        seen[key] = sig

        merged = sorted(seen.values(), key=lambda s: abs(s.score), reverse=True)
        logger.info(
            "scan_with_plugins_finished",
            builtin_count=len(builtin_signals),
            plugin_count=len(plugin_signals),
            merged_count=len(merged),
        )
        return merged
