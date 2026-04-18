import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import logging

import config

logger = logging.getLogger(__name__)


@dataclass
class RiskLevels:
    stop_atr: float = 0.0
    stop_support: float = 0.0
    stop_fibonacci: float = 0.0
    stop_percent: float = 0.0
    stop_swing: float = 0.0

    target_atr: float = 0.0
    target_resistance: float = 0.0
    target_fibonacci: float = 0.0
    target_percent: float = 0.0
    target_swing: float = 0.0

    final_stop: float = 0.0
    final_target: float = 0.0
    risk_reward_ratio: float = 0.0
    risk_pct: float = 0.0
    reward_pct: float = 0.0
    position_size: int = 0
    max_loss_tl: float = 0.0
    risk_budget_tl: float = 0.0
    atr_pct: float = 0.0
    volatility_scale: float = 1.0
    correlation_scale: float = 1.0
    correlated_tickers: list[str] = field(default_factory=list)
    blocked_by_correlation: bool = False

    method_used: str = ""
    confidence: str = "DÜŞÜK"


class RiskManager:
    def __init__(
        self,
        capital: float = None,
        max_risk_per_trade_pct: float = 2.0,
        atr_stop_multiplier: float = 2.0,
        atr_target_multiplier: float = 3.0,
        fixed_stop_pct: float = 5.0,
        fixed_target_pct: float = 8.0,
    ):
        self.capital = capital if capital is not None else getattr(config, "INITIAL_CAPITAL", 8500.0)
        self.max_risk_pct = max_risk_per_trade_pct
        self.atr_stop_mult = atr_stop_multiplier
        self.atr_target_mult = atr_target_multiplier
        self.fixed_stop_pct = fixed_stop_pct
        self.fixed_target_pct = fixed_target_pct
        # Scan-level guard only; this is not a persistent portfolio ledger.
        self._sector_signal_counts = {}
        self.sector_positions = self._sector_signal_counts
        self._portfolio_history: dict[str, pd.DataFrame] = {}
        self.correlation_threshold = float(getattr(config, "CORRELATION_THRESHOLD", 0.70))
        self.correlation_risk_step = float(getattr(config, "CORRELATION_RISK_STEP", 0.35))
        self.correlation_min_scale = float(getattr(config, "CORRELATION_MIN_SCALE", 0.25))
        self.correlation_max_cluster = int(getattr(config, "CORRELATION_MAX_CLUSTER", 2))
        self.atr_baseline_pct = float(getattr(config, "ATR_BASELINE_PCT", 0.025))
        self.atr_min_risk_scale = float(getattr(config, "ATR_MIN_RISK_SCALE", 0.35))

    def check_sector_limit(self, ticker: str) -> bool:
        sector = getattr(config, "SECTOR_MAP", {}).get(ticker)
        if not sector:
            return True
        
        sector_limit = getattr(config, "SECTOR_LIMIT", 2)
        current = self._sector_signal_counts.get(sector, 0)
        
        if current >= sector_limit:
            logger.warning(f"  Sektör limiti: {sector} ({current}/{sector_limit})")
            return False
        
        self._sector_signal_counts[sector] = current + 1
        return True

    def reset_sectors(self):
        self._sector_signal_counts.clear()

    def reset_portfolio(self) -> None:
        self._portfolio_history.clear()

    def get_correlation_matrix(self) -> pd.DataFrame:
        if not self._portfolio_history:
            return pd.DataFrame()

        series_map = {
            ticker: history["close"].astype(float).rename(ticker)
            for ticker, history in self._portfolio_history.items()
            if history is not None and not history.empty and "close" in history.columns
        }
        if not series_map:
            return pd.DataFrame()

        close_frame = pd.concat(series_map.values(), axis=1, join="inner").dropna()
        if close_frame.empty or close_frame.shape[1] < 2:
            return pd.DataFrame(index=close_frame.columns, columns=close_frame.columns)

        returns = close_frame.pct_change().dropna()
        if returns.empty:
            return pd.DataFrame(index=close_frame.columns, columns=close_frame.columns)
        return returns.corr()

    def register_position(self, ticker: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        self._portfolio_history[ticker] = df[[c for c in ["close", "high", "low", "atr"] if c in df.columns]].copy()

    def apply_portfolio_risk(
        self,
        ticker: str,
        df: pd.DataFrame,
        levels: RiskLevels,
    ) -> RiskLevels:
        correlated = self._get_correlated_positions(ticker, df)
        levels.correlated_tickers = correlated

        if len(correlated) > self.correlation_max_cluster:
            levels.blocked_by_correlation = True
            levels.correlation_scale = 0.0
            levels.position_size = 0
            levels.max_loss_tl = 0.0
            levels.risk_budget_tl = 0.0
            logger.warning(f"  Korelasyon limiti: {ticker} -> {', '.join(correlated)}")
            return levels

        correlation_scale = max(
            self.correlation_min_scale,
            1.0 - (len(correlated) * self.correlation_risk_step),
        )
        levels.correlation_scale = round(correlation_scale, 2)
        self._apply_position_budget(price=float(df["close"].iloc[-1]), levels=levels)
        return levels

    def calculate(
        self,
        df: pd.DataFrame,
        direction: str = "LONG"
    ) -> RiskLevels:
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
        atr = df.get("atr")
        if atr is not None and pd.notna(atr.iloc[-1]):
            atr_val = float(atr.iloc[-1])
            levels.stop_atr = round(price - (self.atr_stop_mult * atr_val), 2)
            levels.target_atr = round(price + (self.atr_target_mult * atr_val), 2)
        return levels

    def _calc_support_resistance(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        supports = []
        resistances = []

        for window in [10, 20, 50]:
            if len(df) >= window:
                s = float(df["low"].tail(window).min())
                r = float(df["high"].tail(window).max())
                supports.append(s)
                resistances.append(r)

        if supports:
            valid_supports = [s for s in supports if s < price]
            if valid_supports:
                nearest_support = max(valid_supports)
                levels.stop_support = round(nearest_support * 0.995, 2)

        if resistances:
            valid_resistances = [r for r in resistances if r > price]
            if valid_resistances:
                nearest_resistance = min(valid_resistances)
                levels.target_resistance = round(nearest_resistance, 2)

        return levels

    def _calc_fibonacci(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        lookback = min(60, len(df))
        recent = df.tail(lookback)

        swing_high = float(recent["high"].max())
        swing_low = float(recent["low"].min())
        diff = swing_high - swing_low

        if diff <= 0:
            return levels

        fib_levels = {
            "fib_236": swing_high - (diff * 0.236),
            "fib_382": swing_high - (diff * 0.382),
            "fib_500": swing_high - (diff * 0.500),
            "fib_618": swing_high - (diff * 0.618),
            "fib_786": swing_high - (diff * 0.786),
        }

        below_fibs = {k: v for k, v in fib_levels.items() if v < price}
        if below_fibs:
            nearest_below = max(below_fibs.values())
            levels.stop_fibonacci = round(nearest_below * 0.995, 2)

        above_fibs = {k: v for k, v in fib_levels.items() if v > price}
        if above_fibs:
            nearest_above = min(above_fibs.values())
            levels.target_fibonacci = round(nearest_above, 2)
        else:
            levels.target_fibonacci = round(swing_high, 2)

        return levels

    def _calc_fixed_percent(
        self, price: float, levels: RiskLevels
    ) -> RiskLevels:
        levels.stop_percent = round(
            price * (1 - self.fixed_stop_pct / 100), 2
        )
        levels.target_percent = round(
            price * (1 + self.fixed_target_pct / 100), 2
        )
        return levels

    def _calc_swing_levels(
        self, df: pd.DataFrame, price: float, levels: RiskLevels
    ) -> RiskLevels:
        lookback = min(60, len(df))
        if lookback < 5:
            return levels

        recent = df.tail(lookback).copy()

        swing_low_mask = (
            (recent["low"] < recent["low"].shift(1))
            & (recent["low"] < recent["low"].shift(2))
            & (recent["low"] < recent["low"].shift(-1))
            & (recent["low"] < recent["low"].shift(-2))
        )
        swing_high_mask = (
            (recent["high"] > recent["high"].shift(1))
            & (recent["high"] > recent["high"].shift(2))
            & (recent["high"] > recent["high"].shift(-1))
            & (recent["high"] > recent["high"].shift(-2))
        )

        swing_lows = recent.loc[swing_low_mask, "low"].dropna().astype(float).tolist()
        swing_highs = recent.loc[swing_high_mask, "high"].dropna().astype(float).tolist()

        valid_lows = [s for s in swing_lows if s < price]
        if valid_lows:
            levels.stop_swing = round(max(valid_lows) * 0.995, 2)

        valid_highs = [s for s in swing_highs if s > price]
        if valid_highs:
            levels.target_swing = round(min(valid_highs), 2)

        return levels

    def _determine_final_levels(
        self, price: float, levels: RiskLevels
    ) -> RiskLevels:
        all_stops = {
            "ATR": levels.stop_atr,
            "Destek": levels.stop_support,
            "Fibonacci": levels.stop_fibonacci,
            "Yüzdelik": levels.stop_percent,
            "Swing": levels.stop_swing,
        }

        valid_stops = {k: v for k, v in all_stops.items() if v > 0 and v < price}
        reasonable_stops = {
            k: v for k, v in valid_stops.items()
            if (price - v) / price > 0.01
        }
        reasonable_stops = {
            k: v for k, v in reasonable_stops.items()
            if (price - v) / price < 0.10
        }

        if reasonable_stops:
            best_stop_method = max(reasonable_stops, key=reasonable_stops.get)
            levels.final_stop = reasonable_stops[best_stop_method]
            stop_method = best_stop_method
        elif valid_stops:
            best_stop_method = max(valid_stops, key=valid_stops.get)
            levels.final_stop = valid_stops[best_stop_method]
            stop_method = best_stop_method
        else:
            levels.final_stop = levels.stop_percent
            stop_method = "Yüzdelik"

        all_targets = {
            "ATR": levels.target_atr,
            "Direnç": levels.target_resistance,
            "Fibonacci": levels.target_fibonacci,
            "Yüzdelik": levels.target_percent,
            "Swing": levels.target_swing,
        }

        valid_targets = {k: v for k, v in all_targets.items() if v > price}
        reasonable_targets = {
            k: v for k, v in valid_targets.items()
            if (v - price) / price > 0.02
        }

        if reasonable_targets:
            best_target_method = min(reasonable_targets, key=reasonable_targets.get)
            levels.final_target = reasonable_targets[best_target_method]
            target_method = best_target_method
        elif valid_targets:
            best_target_method = min(valid_targets, key=valid_targets.get)
            levels.final_target = valid_targets[best_target_method]
            target_method = best_target_method
        else:
            levels.final_target = levels.target_percent
            target_method = "Yüzdelik"

        risk = price - levels.final_stop
        reward = levels.final_target - price

        levels.risk_pct = round(-risk / price * 100, 2)
        levels.reward_pct = round(reward / price * 100, 2)
        levels.risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0

        levels.method_used = f"Stop: {stop_method} | Hedef: {target_method}"

        stop_values = [v for v in valid_stops.values()]
        if len(stop_values) >= 3:
            std = np.std(stop_values) / price * 100
            if std < 2:
                levels.confidence = "YÜKSEK"
            elif std < 4:
                levels.confidence = "ORTA"
            else:
                levels.confidence = "DÜŞÜK"
        else:
            levels.confidence = "DÜŞÜK"

        return levels

    def _calc_position_size(
        self, price: float, levels: RiskLevels
    ) -> RiskLevels:
        risk_per_share = price - levels.final_stop

        if risk_per_share <= 0:
            levels.position_size = 0
            levels.max_loss_tl = 0
            return levels

        levels.atr_pct = self._calculate_atr_pct(levels, price)
        levels.volatility_scale = round(self._calculate_risk_throttle(levels.atr_pct), 2)

        self._apply_position_budget(price, levels)

        return levels

    def _apply_position_budget(self, price: float, levels: RiskLevels) -> None:
        risk_per_share = price - levels.final_stop
        if risk_per_share <= 0:
            levels.position_size = 0
            levels.max_loss_tl = 0
            levels.risk_budget_tl = 0
            return

        budget_scale = levels.volatility_scale * levels.correlation_scale
        max_loss_tl = self.capital * (self.max_risk_pct / 100) * budget_scale
        position_size = int(max_loss_tl / risk_per_share) if risk_per_share > 0 else 0

        max_affordable = int(self.capital * 0.9 / price)
        position_size = min(position_size, max_affordable)

        levels.position_size = max(0, position_size)
        levels.max_loss_tl = round(position_size * risk_per_share, 2)
        levels.risk_budget_tl = round(max_loss_tl, 2)

    def _calculate_atr_pct(self, levels: RiskLevels, price: float) -> float:
        if price <= 0 or levels.stop_atr <= 0:
            return 0.0
        atr_distance = abs(price - levels.stop_atr) / max(self.atr_stop_mult, 1e-9)
        return atr_distance / price

    def _calculate_risk_throttle(self, atr_pct: float) -> float:
        if atr_pct <= 0:
            return 1.0
        if atr_pct <= self.atr_baseline_pct:
            return 1.0
        throttle = self.atr_baseline_pct / atr_pct
        return max(self.atr_min_risk_scale, min(1.0, throttle))

    def _get_correlated_positions(self, ticker: str, candidate_df: pd.DataFrame) -> list[str]:
        if not self._portfolio_history:
            return []

        candidate_close = candidate_df[["close"]].rename(columns={"close": ticker}).astype(float)
        correlated = []
        for existing_ticker, history in self._portfolio_history.items():
            existing_close = history[["close"]].rename(columns={"close": existing_ticker}).astype(float)
            aligned = pd.concat([candidate_close, existing_close], axis=1, join="inner").dropna()
            if aligned.empty or len(aligned) < 10:
                continue
            corr = aligned.pct_change().dropna().corr().iloc[0, 1]
            if pd.notna(corr) and abs(float(corr)) >= self.correlation_threshold:
                correlated.append(existing_ticker)
        return correlated


if __name__ == "__main__":
    from data_fetcher import BISTDataFetcher
    from indicators import TechnicalIndicators

    fetcher = BISTDataFetcher()
    ti = TechnicalIndicators()
    rm = RiskManager(capital=getattr(config, "INITIAL_CAPITAL", 8500.0))

    test_tickers = ["ASELS.IS", "THYAO.IS", "BIMAS.IS"]

    for ticker in test_tickers:
        print(f"\n{'='*50}")
        print(f"📊 {ticker}")
        print(f"{'='*50}")

        df = fetcher.fetch_single(ticker, period="6mo")
        if df is not None:
            df = ti.add_all(df)
            levels = rm.calculate(df)

            price = df["close"].iloc[-1]
            print(f"\n  Fiyat: ₺{price:.2f}")
            print(f"  Stop-Loss: ₺{levels.final_stop:.2f} ({levels.risk_pct:+.1f}%)")
            print(f"  Hedef: ₺{levels.final_target:.2f} ({levels.reward_pct:+.1f}%)")
            print(f"  R/R: 1:{levels.risk_reward_ratio:.1f}")
            print(f"  Lot: {levels.position_size}")
            print(f"  Max Kayıp: ₺{levels.max_loss_tl:.2f}")
            print(f"  Yöntem: {levels.method_used}")
