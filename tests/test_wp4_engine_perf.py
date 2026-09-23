"""Performance tests for StrategyEngine optimizations (WP4)."""

from __future__ import annotations

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.strategy import StrategyEngine
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import SignalType


class IdentityIndicators:
    """Pass-through indicators so fixtures fully control scoring inputs."""

    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class FakeRiskLevels:
    final_stop = 95.0
    final_target = 120.0
    confidence = "confidence.medium"
    risk_reward_ratio = 2.0
    method_used = "IntegrationTest"
    position_size = 10
    risk_budget_tl = 200.0
    volatility_scale = 1.0
    atr_pct = 0.02
    correlation_scale = 1.0
    correlated_tickers: list[str] = []
    blocked_by_correlation = False
    signal_probability: float | None = None
    kelly_fraction: float = 0.0
    liquidity_value: float = 0.0


class FakeRiskManagerWithCounter:
    """Risk manager that counts calculate() calls."""

    def __init__(self) -> None:
        self.calculate_calls = 0

    def calculate(self, df: pd.DataFrame) -> FakeRiskLevels:
        self.calculate_calls += 1
        return FakeRiskLevels()

    def apply_portfolio_risk(
        self, ticker: str, df: pd.DataFrame, levels: FakeRiskLevels
    ) -> FakeRiskLevels:
        _ = ticker, df
        return levels

    def apply_signal_probability(
        self,
        df: pd.DataFrame,
        price: float,
        levels: FakeRiskLevels,
        signal_probability: float,
    ) -> FakeRiskLevels:
        _ = df, price, signal_probability
        return levels

    def reset_sectors(self) -> None:
        return None

    def reset_portfolio(self) -> None:
        return None

    def build_global_correlation_cache(self, data: object) -> None:
        _ = data
        return None

    def check_sector_limit(self, ticker: str) -> bool:
        _ = ticker
        return True

    def register_position(self, ticker: str, df: pd.DataFrame) -> None:
        _ = ticker, df
        return None


def _engine(
    params: StrategyParams | None = None,
    risk_manager: FakeRiskManagerWithCounter | None = None,
) -> StrategyEngine:
    return StrategyEngine(
        indicators=IdentityIndicators(),
        risk_manager=risk_manager or FakeRiskManagerWithCounter(),
        params=params or StrategyParams(),
    )


def _row(
    *,
    close: float,
    adx: float,
    plus_di: float,
    minus_di: float,
    rsi: float,
    stoch_k: float,
    stoch_d: float,
    stoch_cross: str,
    cci: float,
    sma_cross: str,
    ema_cross: str,
    macd_cross: str,
    macd_histogram: float,
    macd_hist_increasing: bool,
    di_cross: str,
    bb_position: str,
    bb_percent: float,
    volume: float,
    volume_sma_20: float,
    volume_spike: bool,
    volume_ratio: float,
    price_volume_direction: str,
    price_volume_confirm: bool,
    volume_trend: str,
    obv_trend: str,
    dist_to_support_pct: float,
    dist_to_resistance_pct: float,
    rsi_divergence: str,
    macd_divergence: str,
    ema_long: float,
    sma_fast: float,
    sma_slow: float,
) -> dict[str, float | str | bool]:
    return {
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": volume,
        "volume_sma_20": volume_sma_20,
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
        f"ema_{settings.EMA_LONG}": ema_long,
        "rsi": rsi,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "stoch_cross": stoch_cross,
        "cci": cci,
        "sma_cross": sma_cross,
        "ema_cross": ema_cross,
        "macd_cross": macd_cross,
        "macd_histogram": macd_histogram,
        "macd_hist_increasing": macd_hist_increasing,
        "di_cross": di_cross,
        "bb_position": bb_position,
        "bb_percent": bb_percent,
        "bb_squeeze": False,
        "volume_spike": volume_spike,
        "volume_ratio": volume_ratio,
        "price_volume_direction": price_volume_direction,
        "price_volume_confirm": price_volume_confirm,
        "volume_trend": volume_trend,
        "obv_trend": obv_trend,
        "dist_to_support_pct": dist_to_support_pct,
        "dist_to_resistance_pct": dist_to_resistance_pct,
        "rsi_divergence": rsi_divergence,
        "macd_divergence": macd_divergence,
        f"sma_{settings.SMA_FAST}": sma_fast,
        f"sma_{settings.SMA_SLOW}": sma_slow,
    }


def _frame_from_template(template: dict[str, float | str | bool], n: int = 60) -> pd.DataFrame:
    """Repeat a scoring template across n bars (regime needs >= 50)."""
    return pd.DataFrame([dict(template) for _ in range(n)])


def hold_frame() -> pd.DataFrame:
    """SIDEWAYS + low ADX + neutral components → score near 0 → HOLD."""
    template = _row(
        close=100.0,
        adx=8.0,  # very low ADX
        plus_di=15.0,
        minus_di=15.0,
        rsi=50.0,
        stoch_k=50.0,
        stoch_d=50.0,
        stoch_cross="NONE",
        cci=0.0,
        sma_cross="NONE",
        ema_cross="NONE",
        macd_cross="NONE",
        macd_histogram=0.0,
        macd_hist_increasing=False,
        di_cross="NONE",
        bb_position="MIDDLE",
        bb_percent=0.5,
        volume=1000.0,
        volume_sma_20=1000.0,
        volume_spike=False,
        volume_ratio=1.0,
        price_volume_direction="NEUTRAL",
        price_volume_confirm=False,
        volume_trend="NEUTRAL",
        obv_trend="NEUTRAL",
        dist_to_support_pct=5.0,
        dist_to_resistance_pct=5.0,
        rsi_divergence="NONE",
        macd_divergence="NONE",
        ema_long=100.0,
        sma_fast=100.0,
        sma_slow=100.0,
    )
    return _frame_from_template(template, n=60)


def strong_buy_frame() -> pd.DataFrame:
    """BULL regime + high ADX + extreme bullish components → STRONG_BUY."""
    rows: list[dict[str, float | str | bool]] = []
    for idx in range(60):
        close = 100.0 + idx * 0.25
        rows.append(
            _row(
                close=close,
                adx=30.0,
                plus_di=28.0,
                minus_di=12.0,
                rsi=22.0,
                stoch_k=15.0,
                stoch_d=12.0,
                stoch_cross="BULLISH",
                cci=-120.0,
                sma_cross="GOLDEN_CROSS",
                ema_cross="BULLISH",
                macd_cross="BULLISH",
                macd_histogram=1.0,
                macd_hist_increasing=True,
                di_cross="BULLISH",
                bb_position="BELOW_LOWER",
                bb_percent=0.1,
                volume=3000.0,
                volume_sma_20=1000.0,
                volume_spike=True,
                volume_ratio=3.0,
                price_volume_direction="BULLISH_CONFIRMATION",
                price_volume_confirm=True,
                volume_trend="INCREASING",
                obv_trend="UP",
                dist_to_support_pct=1.0,
                dist_to_resistance_pct=20.0,
                rsi_divergence="BULLISH",
                macd_divergence="BULLISH",
                ema_long=90.0,
                sma_fast=102.0,
                sma_slow=98.0,
            )
        )
    return pd.DataFrame(rows)


def test_session_stats_cache_cleared_after_scan_all() -> None:
    """After scan_all, _session_stats_cache should be empty (cleared in finally)."""
    engine = _engine()
    data = {"TICKER": hold_frame()}
    engine.scan_all(data)
    assert engine._session_stats_cache == {}


def test_risk_calculate_not_called_for_non_buy() -> None:
    """risk_manager.calculate should NOT be called for non-buy signals (HOLD)."""
    risk_manager = FakeRiskManagerWithCounter()
    engine = _engine(risk_manager=risk_manager)
    # Use a frame that we know classifies as HOLD (score near 0)
    signal = engine.analyze("HOLD.IS", hold_frame())
    # For this fixture, we expect HOLD (score ~0)
    assert signal is None  # HOLD returns None from analyze
    assert risk_manager.calculate_calls == 0


def test_risk_calculate_called_for_buy() -> None:
    """risk_manager.calculate should be called at least once for BUY signals."""
    risk_manager = FakeRiskManagerWithCounter()
    engine = _engine(risk_manager=risk_manager)
    signal = engine.analyze("BUY.IS", strong_buy_frame())
    assert signal is not None
    assert signal.signal_type is SignalType.STRONG_BUY
    assert risk_manager.calculate_calls >= 1
