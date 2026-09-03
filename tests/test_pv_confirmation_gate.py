"""Deney F: pv_confirmation_required gate tests.

Default off = mevcut davranış birebir aynı. Açıkken long aday
(price_volume_direction != BULLISH_CONFIRMATION) reddedilir; teyitli aday
geçer. Kısa taraf (short) etkilenmez.
"""

from __future__ import annotations

import pandas as pd

from bist_bot.strategy.engine_filters import calculate_score_and_reasons
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import check_momentum_confirmation
from bist_bot.strategy.scoring import (
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)


def _frame(n: int = 120, pv: str = "NONE") -> pd.DataFrame:
    """Golden-cross trending frame; skor buy_threshold (25) üstüne çıkar."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rows = []
    for i, d in enumerate(dates):
        close = 100.0 + i * 0.5
        rows.append(
            {
                "date": d,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close + 0.1,
                "volume": 10_000.0,
                "volume_sma_20": 10_000.0,
                "atr": 1.5,
                "rsi": 28.0,
                "sma_cross": "GOLDEN_CROSS",
                "macd_cross": "BULLISH",
                "bb_position": "BELOW_LOWER",
                "sma_5": close + 0.5,
                "sma_20": close - 0.5,
                "ema_200": close - 5.0,
                "adx": 25.0,
                "plus_di": 30.0,
                "minus_di": 10.0,
                "price_volume_direction": pv,
                "obv_trend": "FLAT",
            }
        )
    return pd.DataFrame(rows).set_index("date")


def _score(params: StrategyParams, df: pd.DataFrame):
    last, prev = df.iloc[-1], df.iloc[-2]
    return calculate_score_and_reasons(
        params,
        "T.IS",
        df,
        last=last,
        prev=prev,
        momentum_scorer=lambda lst, pr: score_momentum(params, lst, pr),
        trend_scorer=lambda lst, pr, d=None: score_trend(params, lst, pr, d),  # type: ignore[misc]  # default arg blocks inference; matches ScoreThreeRows at runtime
        volume_scorer=lambda lst, pr: score_volume(params, lst, pr),
        structure_scorer=lambda lst: score_structure(params, lst),
        momentum_checker=check_momentum_confirmation,
    )


def test_default_off_preserves_behaviour():
    params = StrategyParams.conservative()
    assert params.pv_confirmation_required is False
    df = _frame(pv="NONE")
    result = _score(params, df)
    assert result is not None
    score, _, _ = result
    assert score >= params.buy_threshold


def test_gate_blocks_unconfirmed_long_candidate():
    params = StrategyParams.conservative()
    params.pv_confirmation_required = True
    df = _frame(pv="NONE")
    assert _score(params, df) is None


def test_gate_blocks_bearish_pv_long_candidate():
    params = StrategyParams.conservative()
    params.pv_confirmation_required = True
    df = _frame(pv="BEARISH_CONFIRMATION")
    # BEARISH pv skoru 25 altına düşürür (aday değil) → kapıya gerek kalmadan
    # sinyal üretilmez; skorun eşik altında kaldığını doğrula.
    result = _score(params, df)
    if result is not None:
        score, _, _ = result
        assert score < params.buy_threshold


def test_gate_passes_bullish_pv_long_candidate():
    params = StrategyParams.conservative()
    params.pv_confirmation_required = True
    df = _frame(pv="BULLISH_CONFIRMATION")
    result = _score(params, df)
    assert result is not None
    score, _, _ = result
    assert score >= params.buy_threshold


def test_gate_does_not_affect_below_threshold_rows():
    params = StrategyParams.conservative()
    params.pv_confirmation_required = True
    df = _frame(pv="NONE")
    # buy_threshold'u erişilmez yap → skor aday değil, kapı devreye girmez.
    params.buy_threshold = 10_000.0
    result = _score(params, df)
    assert result is not None
    score, _, _ = result
    assert score < 10_000.0


def test_gate_short_side_untouched():
    params = StrategyParams.conservative()
    params.pv_confirmation_required = True
    # Düşüş trendi / negatif skor senaryosu: skor negatif çıkmalı ve
    # gate (score >= buy_threshold iken çalıştığı için) kısa tarafı engellememelidir.
    df = _frame(pv="NONE")
    # SMA death cross ve bearish indikatörler ile düşüş çerçevesi oluştur
    df["sma_cross"] = "DEATH_CROSS"
    df["macd_cross"] = "BEARISH"
    df["rsi"] = 75.0
    df["bb_position"] = "ABOVE_UPPER"
    result = _score(params, df)
    assert result is not None
    score, reasons, _ = result
    assert score < 0  # negatif skorlu sat/short aday engellenmedi (None dönmedi)
