"""Risk manager facade composed from domain modules."""

from __future__ import annotations

from bist_bot.app_logging import get_logger
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, cast, Protocol

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.risk import correlation as correlation_helpers
from bist_bot.risk.models import RiskLevels
from bist_bot.risk import sizing as sizing_helpers
from bist_bot.risk import stops as stop_helpers

logger = get_logger(__name__, component="risk_manager")
TR = timezone(timedelta(hours=3))


class _HasActivePositions(Protocol):
    def get_active_position_tickers(self) -> list[str]: ...


class RiskManager:
    def __init__(
        self,
        capital: float | None = None,
        max_risk_per_trade_pct: float = 2.0,
        atr_stop_multiplier: float = 2.0,
        atr_target_multiplier: float = 3.0,
        fixed_stop_pct: float = 5.0,
        fixed_target_pct: float = 8.0,
        position_repository: _HasActivePositions | None = None,
    ):
        if capital is not None and capital <= 0:
            raise ValueError("capital must be greater than zero")
        self.capital = (
            float(capital)
            if capital is not None
            else float(getattr(settings, "INITIAL_CAPITAL", 8500.0))
        )
        self.max_risk_pct = max_risk_per_trade_pct
        self.atr_stop_mult = atr_stop_multiplier
        self.atr_target_mult = atr_target_multiplier
        self.fixed_stop_pct = fixed_stop_pct
        self.fixed_target_pct = fixed_target_pct
        self.position_repository = position_repository
        self._sector_signal_counts: dict[str, int] = {}
        self.sector_positions = self._sector_signal_counts
        self._portfolio_history: dict[str, pd.DataFrame] = {}
        self._global_corr_cache: Optional[pd.DataFrame] = None
        self.correlation_threshold = float(
            getattr(settings, "CORRELATION_THRESHOLD", 0.70)
        )
        self.correlation_risk_step = float(
            getattr(settings, "CORRELATION_RISK_STEP", 0.35)
        )
        self.correlation_min_scale = float(
            getattr(settings, "CORRELATION_MIN_SCALE", 0.25)
        )
        self.correlation_max_cluster = int(
            getattr(settings, "CORRELATION_MAX_CLUSTER", 2)
        )
        self.atr_baseline_pct = float(getattr(settings, "ATR_BASELINE_PCT", 0.025))
        self.atr_min_risk_scale = float(getattr(settings, "ATR_MIN_RISK_SCALE", 0.35))
        self.max_position_cap_pct = float(
            getattr(settings, "MAX_POSITION_CAP_PCT", 90.0)
        )
        self.kelly_fraction_scale = float(
            getattr(settings, "KELLY_FRACTION_SCALE", 0.25)
        )
        self.min_signal_probability = float(
            getattr(settings, "MIN_SIGNAL_PROBABILITY", 0.50)
        )
        self.min_liquidity_value_tl = float(
            getattr(settings, "MIN_LIQUIDITY_VALUE_TL", 0.0)
        )
        self.daily_loss_cap_pct = float(getattr(settings, "DAILY_LOSS_CAP_PCT", 0.0))
        self.daily_realized_pnl = 0.0
        self._daily_realized_pnl_date = self._today()

    def _today(self):
        return datetime.now(TR).date()

    def _roll_daily_realized_pnl_if_needed(self) -> None:
        today = self._today()
        if today != self._daily_realized_pnl_date:
            self.daily_realized_pnl = 0.0
            self._daily_realized_pnl_date = today

    def check_sector_limit(self, ticker: str) -> bool:
        sector = getattr(settings, "SECTOR_MAP", {}).get(ticker)
        if not sector:
            return True
        sector_limit = getattr(settings, "SECTOR_LIMIT", 2)
        current = self._sector_signal_counts.get(sector, 0)
        if current >= sector_limit:
            logger.warning("sector_limit_reached", sector=sector, current=current, limit=sector_limit)
            return False
        self._sector_signal_counts[sector] = current + 1
        return True

    def reset_sectors(self):
        self._sector_signal_counts.clear()

    @contextmanager
    def sector_scan(self):
        self.reset_sectors()
        try:
            yield self
        finally:
            self.reset_sectors()

    def reset_portfolio(self) -> None:
        self._portfolio_history.clear()
        self._global_corr_cache = None

    def set_daily_realized_pnl(self, amount: float) -> None:
        self._roll_daily_realized_pnl_if_needed()
        self.daily_realized_pnl = float(amount)

    def daily_loss_limit_reached(self) -> bool:
        self._roll_daily_realized_pnl_if_needed()
        if self.daily_loss_cap_pct <= 0:
            return False
        return self.daily_realized_pnl <= -(
            self.capital * self.daily_loss_cap_pct / 100.0
        )

    def build_global_correlation_cache(self, data: dict) -> None:
        self._global_corr_cache = correlation_helpers.build_global_correlation_cache(
            data
        )
        self._restore_persisted_positions(data)

    def get_correlation_matrix(self) -> pd.DataFrame:
        return correlation_helpers.get_correlation_matrix(self._portfolio_history)

    def register_position(self, ticker: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        history_slice = cast(
            pd.DataFrame,
            df[[c for c in ["close", "high", "low", "atr"] if c in df.columns]].copy(),
        )
        self._portfolio_history[ticker] = history_slice

    def _restore_persisted_positions(self, data: dict) -> None:
        if self.position_repository is None or not hasattr(
            self.position_repository, "get_active_position_tickers"
        ):
            return

        for ticker in self.position_repository.get_active_position_tickers():
            if ticker in self._portfolio_history:
                continue
            market_data = data.get(ticker)
            if market_data is None:
                continue
            if isinstance(market_data, dict):
                df = market_data.get("trend")
                if df is None:
                    df = market_data.get("trigger")
            else:
                df = market_data
            if df is None or df.empty:
                continue
            self.register_position(ticker, cast(pd.DataFrame, df))

    def apply_portfolio_risk(
        self, ticker: str, df: pd.DataFrame, levels: RiskLevels
    ) -> RiskLevels:
        return correlation_helpers.apply_portfolio_risk(
            ticker=ticker,
            df=df,
            levels=levels,
            portfolio_history=self._portfolio_history,
            global_corr_cache=self._global_corr_cache,
            correlation_threshold=self.correlation_threshold,
            correlation_max_cluster=self.correlation_max_cluster,
            correlation_min_scale=self.correlation_min_scale,
            correlation_risk_step=self.correlation_risk_step,
            capital=self.capital,
            max_risk_pct=self.max_risk_pct,
        )

    def calculate(self, df: pd.DataFrame, direction: str = "LONG") -> RiskLevels:
        _ = direction
        if df is None or len(df) < 20:
            return RiskLevels()

        price = float(df["close"].iloc[-1])
        levels = RiskLevels()
        levels = self._calc_atr_levels(df, price, levels)
        levels = self._calc_support_resistance(df, price, levels)
        levels = self._calc_fibonacci(df, price, levels)
        levels = self._calc_fixed_percent(price, levels)
        levels = self._calc_swing_levels(df, price, levels)
        levels = self._determine_final_levels(price, levels)
        levels = self._calc_position_size(price, levels)
        return levels

    def _calc_atr_levels(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        return stop_helpers.calc_atr_levels(
            df, price, levels, self.atr_stop_mult, self.atr_target_mult
        )

    def _calc_support_resistance(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        return stop_helpers.calc_support_resistance(df, price, levels)

    def _calc_fibonacci(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        return stop_helpers.calc_fibonacci(df, price, levels)

    def _calc_fixed_percent(self, price: float, levels: RiskLevels) -> RiskLevels:
        return stop_helpers.calc_fixed_percent(
            price, levels, self.fixed_stop_pct, self.fixed_target_pct
        )

    def _calc_swing_levels(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        return stop_helpers.calc_swing_levels(df, price, levels)

    def _determine_final_levels(self, price: float, levels: RiskLevels) -> RiskLevels:
        return stop_helpers.determine_final_levels(price, levels)

    def _calc_position_size(self, price: float, levels: RiskLevels) -> RiskLevels:
        return sizing_helpers.calc_position_size(
            price,
            levels,
            self.capital,
            self.max_risk_pct,
            self.atr_stop_mult,
            self.atr_baseline_pct,
            self.atr_min_risk_scale,
            self.max_position_cap_pct,
        )

    def _apply_position_budget(self, price: float, levels: RiskLevels) -> None:
        sizing_helpers.apply_position_budget(
            price,
            levels,
            self.capital,
            self.max_risk_pct,
            self.max_position_cap_pct,
        )

    def apply_signal_probability(
        self,
        df: pd.DataFrame,
        price: float,
        levels: RiskLevels,
        signal_probability: float,
    ) -> RiskLevels:
        liquidity_value = 0.0
        if "close" in df.columns and "volume" in df.columns and not df.empty:
            recent = cast(pd.DataFrame, df[["close", "volume"]].tail(20).copy())
            liquidity_series = recent["close"].astype(float) * recent["volume"].astype(
                float
            )
            liquidity_value = (
                float(liquidity_series.mean()) if not liquidity_series.empty else 0.0
            )
        return sizing_helpers.apply_probability_sizing(
            price,
            levels,
            self.capital,
            signal_probability=signal_probability,
            kelly_fraction_scale=self.kelly_fraction_scale,
            max_position_cap_pct=self.max_position_cap_pct,
            min_signal_probability=self.min_signal_probability,
            liquidity_value=liquidity_value,
            min_liquidity_value=self.min_liquidity_value_tl,
            daily_loss_limit_reached=self.daily_loss_limit_reached(),
        )

    def _calculate_atr_pct(self, levels: RiskLevels, price: float) -> float:
        return sizing_helpers.calculate_atr_pct(levels, price, self.atr_stop_mult)

    def _calculate_risk_throttle(self, atr_pct: float) -> float:
        return sizing_helpers.calculate_risk_throttle(
            atr_pct, self.atr_baseline_pct, self.atr_min_risk_scale
        )

    def _get_correlated_positions(
        self, ticker: str, candidate_df: pd.DataFrame
    ) -> list[str]:
        return correlation_helpers.get_correlated_positions(
            ticker,
            candidate_df,
            self._portfolio_history,
            self._global_corr_cache,
            self.correlation_threshold,
        )
