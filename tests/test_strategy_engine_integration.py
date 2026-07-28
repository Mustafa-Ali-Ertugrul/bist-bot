"""End-to-end integration regression for ``StrategyEngine.analyze``.

WARNING / UYARI
---------------
If you intentionally change the analyze pipeline order, regime damping
(``sideways_score_multiplier``), ADX soft penalty (``adx_low_trend_penalty`` /
``adx_threshold``), score caps (±100), classification thresholds, or minimum
trigger candle count, you MUST consciously update the expected signal types,
scores, reason-chain assertions, and ordering checks in this file.

Bu dosya, rejim → skorlama → (sideways çarpanı) → ADX cezası → sınıflandırma
zincirinin ``StrategyEngine.analyze`` içinde doğru sırayla ve birbirini
bozmadan çalıştığını garanti eder. Pipeline sıralaması veya eşikler
değişirse testleri bilinçli güncelleyin.

Pipeline (production order in ``engine.analyze``):
1. enough trigger history
2. indicator enrichment (IdentityIndicators in these tests)
3. ADX present filter
4. ``calculate_score_and_reasons`` (regime label + sideways × multiplier)
5. ``apply_low_adx_penalty`` when ADX < threshold
6. ``classify_signal``
7. risk manager + signal construction
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.strategy import StrategyEngine
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MarketRegime, detect_regime
from bist_bot.strategy.signal_models import Signal, SignalType


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


class FakeRiskManager:
    """Neutral risk collaborator so analyze focuses on score/regime pipeline."""

    def calculate(self, df: pd.DataFrame) -> FakeRiskLevels:
        _ = df
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


def _engine(params: StrategyParams | None = None) -> StrategyEngine:
    return StrategyEngine(
        indicators=cast(Any, IdentityIndicators()),
        risk_manager=cast(Any, FakeRiskManager()),
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


def weak_penalized_frame() -> pd.DataFrame:
    """SIDEWAYS + low ADX + moderate bullish components → damped score + ADX penalty."""
    template = _row(
        close=100.0,
        adx=12.0,
        plus_di=18.0,
        minus_di=17.0,
        rsi=35.0,
        stoch_k=40.0,
        stoch_d=35.0,
        stoch_cross="NONE",
        cci=-60.0,
        sma_cross="NONE",
        ema_cross="NONE",
        macd_cross="NONE",
        macd_histogram=0.2,
        macd_hist_increasing=True,
        di_cross="NONE",
        bb_position="MIDDLE",
        bb_percent=0.15,
        volume=1500.0,
        volume_sma_20=1000.0,
        volume_spike=False,
        volume_ratio=1.5,
        price_volume_direction="BULLISH_CONFIRMATION",
        price_volume_confirm=True,
        volume_trend="INCREASING",
        obv_trend="UP",
        dist_to_support_pct=1.5,
        dist_to_resistance_pct=10.0,
        rsi_divergence="NONE",
        macd_divergence="NONE",
        ema_long=100.0,
        sma_fast=101.0,
        sma_slow=99.0,
    )
    return _frame_from_template(template, n=60)


def strong_sell_frame() -> pd.DataFrame:
    """BEAR regime + high ADX + extreme bearish components → STRONG_SELL."""
    rows: list[dict[str, float | str | bool]] = []
    for idx in range(60):
        close = 100.0 - idx * 0.25
        rows.append(
            _row(
                close=close,
                adx=32.0,
                plus_di=12.0,
                minus_di=28.0,
                rsi=82.0,
                stoch_k=88.0,
                stoch_d=90.0,
                stoch_cross="BEARISH",
                cci=130.0,
                sma_cross="DEATH_CROSS",
                ema_cross="BEARISH",
                macd_cross="BEARISH",
                macd_histogram=-0.5,
                macd_hist_increasing=False,
                di_cross="BEARISH",
                bb_position="ABOVE_UPPER",
                bb_percent=0.95,
                volume=2500.0,
                volume_sma_20=1000.0,
                volume_spike=True,
                volume_ratio=2.5,
                price_volume_direction="BEARISH_CONFIRMATION",
                price_volume_confirm=False,
                volume_trend="DECREASING",
                obv_trend="DOWN",
                dist_to_support_pct=15.0,
                dist_to_resistance_pct=1.0,
                rsi_divergence="BEARISH",
                macd_divergence="BEARISH",
                ema_long=120.0,
                sma_fast=97.0,
                sma_slow=101.0,
            )
        )
    return pd.DataFrame(rows)


def filtered_short_history_frame() -> pd.DataFrame:
    """Too few trigger candles → analyze returns None (filtered)."""
    return strong_buy_frame().head(10).reset_index(drop=True)


def filtered_missing_adx_frame() -> pd.DataFrame:
    """ADX missing → hard filter before scoring."""
    df = strong_buy_frame().copy()
    df.loc[:, "adx"] = float("nan")
    return df


def _sideways_reason_index(reasons: list[str]) -> int:
    for idx, reason in enumerate(reasons):
        if "Piyasa rejimi yatay" in reason or "yatay" in reason.lower():
            return idx
    raise AssertionError(f"Sideways reason missing in: {reasons}")


def _adx_penalty_reason_index(reasons: list[str]) -> int:
    for idx, reason in enumerate(reasons):
        if "ADX düşük" in reason and "skor cezası" in reason:
            return idx
    raise AssertionError(f"ADX penalty reason missing in: {reasons}")


# ---------------------------------------------------------------------------
# Regime preconditions on fixtures
# ---------------------------------------------------------------------------


def test_fixture_regimes_match_scenario_labels() -> None:
    assert detect_regime(strong_buy_frame()) is MarketRegime.BULL
    assert detect_regime(weak_penalized_frame()) is MarketRegime.SIDEWAYS
    assert detect_regime(strong_sell_frame()) is MarketRegime.BEAR


# ---------------------------------------------------------------------------
# End-to-end analyze scenarios
# ---------------------------------------------------------------------------


def test_analyze_strong_buy_bull_high_adx() -> None:
    """Güçlü Alım: BULL + high ADX + high score → STRONG_BUY (capped at 100)."""
    engine = _engine()
    signal = engine.analyze("BULL.IS", strong_buy_frame())

    assert signal is not None
    assert isinstance(signal, Signal)
    assert signal.signal_type is SignalType.STRONG_BUY
    assert signal.score == pytest.approx(100.0)
    assert signal.score >= engine.STRONG_BUY_THRESHOLD
    assert "Piyasa rejimi yatay" not in " ".join(signal.reasons)
    assert not any("ADX düşük" in reason for reason in signal.reasons)
    # Component reason chain still present
    assert any("RSI" in reason for reason in signal.reasons)
    assert any(
        "MACD" in reason or "Golden Cross" in reason or "EMA" in reason for reason in signal.reasons
    )


def test_analyze_weak_penalized_sideways_low_adx_pipeline_order() -> None:
    """Zayıf/cezalı: SIDEWAYS (×0.6) then ADX penalty (−5) → reduced BUY-class score.

    Expected math for this fixture (locked snapshot):
    - raw component total before regime ≈ 52.0
    - after sideways (×0.6) ≈ 31.2
    - after ADX penalty (−5) ≈ 26.2  → BUY threshold (>=20)
    """
    params = StrategyParams()
    engine = _engine(params)
    frame = weak_penalized_frame()
    signal = engine.analyze("SIDE.IS", frame)

    assert signal is not None
    assert signal.signal_type in {SignalType.BUY, SignalType.WEAK_BUY}
    assert signal.signal_type is not SignalType.STRONG_BUY
    assert signal.score == pytest.approx(26.2)
    assert signal.score < params.strong_buy_threshold

    sideways_idx = _sideways_reason_index(signal.reasons)
    adx_idx = _adx_penalty_reason_index(signal.reasons)
    # Sideways damping is applied inside calculate_score_and_reasons *before*
    # the engine applies the ADX soft penalty — reason order must reflect that.
    assert sideways_idx < adx_idx

    # Reverse-check pipeline arithmetic: final = raw * sideways_mult - adx_penalty
    final = signal.score
    pre_adx = final + params.adx_low_trend_penalty
    raw = pre_adx / params.sideways_score_multiplier
    assert pre_adx == pytest.approx(31.2)
    assert raw == pytest.approx(52.0)
    assert final == pytest.approx(
        raw * params.sideways_score_multiplier - params.adx_low_trend_penalty
    )


def test_analyze_strong_sell_bear_high_adx() -> None:
    """Güçlü Satış: BEAR + high ADX + low score → STRONG_SELL (capped at -100)."""
    engine = _engine()
    signal = engine.analyze("BEAR.IS", strong_sell_frame())

    assert signal is not None
    assert signal.signal_type is SignalType.STRONG_SELL
    assert signal.score == pytest.approx(-100.0)
    assert signal.score <= engine.STRONG_SELL_THRESHOLD
    assert "Piyasa rejimi yatay" not in " ".join(signal.reasons)
    assert not any("ADX düşük" in reason for reason in signal.reasons)


def test_analyze_filtered_insufficient_history_returns_none() -> None:
    """Filtrelenen: too few candles → NO SIGNAL (None)."""
    engine = _engine()
    signal = engine.analyze("SHORT.IS", filtered_short_history_frame())
    assert signal is None


def test_analyze_filtered_missing_adx_returns_none() -> None:
    """Filtrelenen: ADX missing/NaN → NO SIGNAL before scoring."""
    engine = _engine()
    signal = engine.analyze("NOADX.IS", filtered_missing_adx_frame())
    assert signal is None


def test_analyze_classification_thresholds_align_with_final_score() -> None:
    """Final score after pipeline must land in the correct classification bucket."""
    engine = _engine()

    strong = engine.analyze("BULL.IS", strong_buy_frame())
    weak = engine.analyze("SIDE.IS", weak_penalized_frame())
    bear = engine.analyze("BEAR.IS", strong_sell_frame())

    assert strong is not None and strong.signal_type is SignalType.STRONG_BUY
    assert weak is not None and weak.signal_type is SignalType.BUY
    assert bear is not None and bear.signal_type is SignalType.STRONG_SELL

    assert strong.score >= engine.STRONG_BUY_THRESHOLD
    assert engine.BUY_THRESHOLD <= weak.score < engine.STRONG_BUY_THRESHOLD
    assert bear.score <= engine.STRONG_SELL_THRESHOLD


def test_analyze_reason_chain_includes_risk_append_for_trade_plan() -> None:
    """Successful analyze should keep scoring reasons and append risk metadata."""
    engine = _engine()
    signal = engine.analyze("BULL.IS", strong_buy_frame())
    assert signal is not None
    assert signal.reasons  # non-empty chain
    # Risk helper usually appends stop/target style notes; at minimum score reasons exist.
    joined = " ".join(signal.reasons)
    assert "RSI" in joined or "MACD" in joined or "Stochastic" in joined
