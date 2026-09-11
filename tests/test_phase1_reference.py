"""Aşama 1 değişiklik-öncesi davranış referansı (golden).

Bu dosya, parametre taşıma (Step 1) ve korelasyon cache'i (Step 2) ÖNCESİNDE
mevcut davranışı sabitler. Buradaki hiçbir beklenen değer, env override
yokken yapılan refaktörle değişmemelidir; değişirse refaktör değil davranış
değişikliğidir ve ayrı karar gerektirir.
"""

import numpy as np
import pandas as pd

from bist_bot.risk import correlation as corr
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.scoring import (
    combine_component_scores,
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)
from bist_bot.strategy.signal_models import (
    SignalCategory,
    SignalType,
    categorize,
    categorize_signal,
)


def _bullish_oversold_last() -> pd.Series:
    return pd.Series(
        {
            "close": 95.0,
            "rsi": 22.0,
            "stoch_k": 15.0,
            "stoch_d": 12.0,
            "stoch_cross": "BULLISH",
            "cci": -120.0,
            "adx": 28.0,
            "ema_200": 100.0,
            "sma_cross": "NONE",
            "sma_5": 96.0,
            "sma_20": 98.0,
            "ema_cross": "NONE",
            "macd_cross": "BULLISH",
            "macd_histogram": 0.5,
            "macd_hist_increasing": True,
            "plus_di": 30.0,
            "minus_di": 15.0,
            "di_cross": "BULLISH",
            "volume": 5000.0,
            "volume_sma_20": 1000.0,
            "volume_spike": True,
            "volume_ratio": 5.0,
            "price_volume_direction": "BULLISH_CONFIRMATION",
            "price_volume_confirm": True,
            "volume_trend": "INCREASING",
            "obv_trend": "UP",
            "bb_position": "BELOW_LOWER",
            "bb_percent": 0.05,
            "bb_squeeze": True,
            "dist_to_support_pct": 1.0,
            "dist_to_resistance_pct": 12.0,
            "rsi_divergence": "BULLISH",
            "macd_divergence": "NONE",
        }
    )


def _score_all(params: StrategyParams) -> dict[str, float]:
    last = _bullish_oversold_last()
    prev = pd.Series({"close": 94.0, "ema_200": 100.0})
    momentum, _ = score_momentum(params, last, prev)
    trend, _ = score_trend(params, last, prev)
    volume, _ = score_volume(params, last, prev)
    structure, _ = score_structure(params, last)
    total, _ = combine_component_scores(params, momentum, trend, volume, structure)
    return {
        "momentum": float(momentum),
        "trend": float(trend),
        "volume": float(volume),
        "structure": float(structure),
        "total": float(total),
    }


def test_reference_default_profile_scores() -> None:
    assert _score_all(StrategyParams()) == {
        "momentum": 43.0,
        "trend": 23.0,
        "volume": 24.0,
        "structure": 31.0,
        "total": 121.0,
    }


def test_reference_champion_profile_scores() -> None:
    assert _score_all(StrategyParams.champion_wr()) == {
        "momentum": 32.5,
        "trend": 23.0,
        "volume": 24.0,
        "structure": 31.0,
        "total": 110.5,
    }


def test_reference_categorize_cap_default_binds() -> None:
    # Varsayılan cap 33: skor 50, eşik 25 -> AL (cap eşik üstünde kalır).
    assert categorize(SignalType.BUY, 50.0, 25.0) == SignalCategory.AL
    # Skor 50, eşik 40 -> cap bağlar (33 < 40) -> RADAR.
    assert categorize(SignalType.BUY, 50.0, 40.0) == SignalCategory.RADAR
    # Açık override cap'i kaldırır.
    assert categorize(SignalType.BUY, 50.0, 40.0, max_signal_score=100.0) == SignalCategory.AL


def test_reference_categorize_signal_cap_override() -> None:
    from datetime import UTC, datetime

    from bist_bot.strategy.signal_models import Signal

    sig = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=50.0,
        price=300.0,
        buy_threshold=40.0,
        timestamp=datetime.now(UTC),
    )
    assert categorize_signal(sig) == SignalCategory.RADAR
    assert categorize_signal(sig, max_signal_score=100.0) == SignalCategory.AL


def _corr_universe(n: int = 60) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(7)
    base = 100 + np.cumsum(rng.normal(0.2, 1.0, n))
    return {
        "AAA.IS": pd.DataFrame({"close": base}),
        "BBB.IS": pd.DataFrame({"close": base * 1.5 + 3.0}),
        "CCC.IS": pd.DataFrame({"close": 100 + np.cumsum(rng.normal(0.0, 2.0, n))}),
    }


def test_reference_correlation_matrix_values() -> None:
    matrix = corr.build_global_correlation_cache(_corr_universe())
    assert matrix is not None
    assert matrix.shape == (3, 3)
    assert round(float(matrix.loc["AAA.IS", "BBB.IS"]), 6) == 1.0
    assert round(float(matrix.loc["AAA.IS", "CCC.IS"]), 6) == 0.056001


def test_reference_correlated_positions_threshold() -> None:
    data = _corr_universe()
    matrix = corr.build_global_correlation_cache(data)
    found = corr.get_correlated_positions(
        "AAA.IS",
        data["AAA.IS"],
        {"BBB.IS": data["BBB.IS"], "CCC.IS": data["CCC.IS"]},
        matrix,
        0.70,
    )
    assert found == ["BBB.IS"]


def test_reference_pairwise_fallback_min_bars() -> None:
    data = _corr_universe()
    # 9 örtüşen bar -> yetersiz, boş liste (mevcut davranış).
    got9 = corr.get_correlated_positions(
        "AAA.IS",
        data["AAA.IS"].tail(9),
        {"BBB.IS": data["BBB.IS"].tail(9)},
        None,
        0.70,
    )
    assert got9 == []
    # 10 örtüşen bar -> hesaplanır (mevcut davranış).
    got10 = corr.get_correlated_positions(
        "AAA.IS",
        data["AAA.IS"].tail(10),
        {"BBB.IS": data["BBB.IS"].tail(10)},
        None,
        0.70,
    )
    assert got10 == ["BBB.IS"]
