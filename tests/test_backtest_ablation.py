from __future__ import annotations

from datetime import datetime

import pandas as pd

from bist_bot.backtest import Backtester, BacktestMode
from bist_bot.ml.training import (
    LabelDefinition,
    SplitConfig,
    train_meta_model_from_dataset,
)


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class DummyMetaModel:
    def predict_probability(self, features: dict[str, float]) -> float:
        return 0.7 if features["score"] >= 35 else 0.53


def build_ablation_frame(periods: int = 120) -> pd.DataFrame:
    rows = []
    dates = pd.date_range(datetime(2024, 1, 1), periods=periods, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 24
        base = 100 + idx * 0.25
        if phase < 6:
            close = base + 1.0
            high = close + 2.0
            low = base - 1.0
            rsi = 22.0
            sma_cross = "GOLDEN_CROSS" if phase == 0 else "NONE"
            macd_cross = "BULLISH"
            bb_position = "BELOW_LOWER"
            sma_fast = base + 1.5
            sma_slow = base - 1.0
        elif 6 <= phase < 12:
            close = base - 1.5
            high = base + 0.5
            low = close - 2.5
            rsi = 76.0
            sma_cross = "DEATH_CROSS" if phase == 6 else "NONE"
            macd_cross = "BEARISH"
            bb_position = "ABOVE_UPPER"
            sma_fast = base - 1.5
            sma_slow = base + 1.0
        else:
            close = base + 0.2
            high = close + 0.7
            low = close - 0.7
            rsi = 50.0
            sma_cross = "NONE"
            macd_cross = "NONE"
            bb_position = "MIDDLE"
            sma_fast = base + 0.3
            sma_slow = base
        rows.append(
            {
                "date": date,
                "open": base,
                "high": high,
                "low": low,
                "close": close,
                "volume": 50000,
                "volume_sma_20": 50000,
                "atr": 2.0,
                "rsi": rsi,
                "sma_cross": sma_cross,
                "macd_cross": macd_cross,
                "bb_position": bb_position,
                "sma_5": sma_fast,
                "sma_20": sma_slow,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def test_backtest_ablation_runs_all_three_modes() -> None:
    df = build_ablation_frame()
    backtester = Backtester(
        initial_capital=10000,
        indicators=IdentityIndicators(),
        meta_model=DummyMetaModel(),
        min_probability=0.6,
        fractional_kelly=0.25,
        max_position_cap_pct=20.0,
    )

    result = backtester.run_ablation("TEST.IS", df, verbose=False)

    assert set(result.runs) == {
        BacktestMode.BASE_FIXED_SIZE.value,
        BacktestMode.META_FILTER_FIXED_SIZE.value,
        BacktestMode.META_FILTER_FRACTIONAL_KELLY.value,
    }
    assert "sharpe_ratio" in result.comparisons[BacktestMode.META_FILTER_FIXED_SIZE.value]
    assert (
        result.runs[BacktestMode.META_FILTER_FRACTIONAL_KELLY.value].mode
        == BacktestMode.META_FILTER_FRACTIONAL_KELLY.value
    )


def test_meta_backtest_reports_probability_diagnostics() -> None:
    df = build_ablation_frame()
    backtester = Backtester(
        initial_capital=10000,
        indicators=IdentityIndicators(),
        meta_model=DummyMetaModel(),
        mode=BacktestMode.META_FILTER_FRACTIONAL_KELLY,
        min_probability=0.5,
        fractional_kelly=0.25,
        max_position_cap_pct=20.0,
    )

    result = backtester.run("TEST.IS", df, verbose=False)

    assert result is not None
    assert result.probability_diagnostics["brier_score"] >= 0.0
    assert len(result.probability_diagnostics["probability_buckets"]) == 4
    assert result.turnover_ratio >= 0.0
    assert result.exposure_pct >= 0.0


def test_backtest_ablation_accepts_loaded_training_artifact(tmp_path) -> None:
    training_rows = []
    dates = pd.date_range(datetime(2024, 1, 1), periods=80, freq="D")
    for idx, date in enumerate(dates):
        label = 1 if idx % 4 in {2, 3} else 0
        training_rows.append(
            {
                "ticker": "TEST.IS",
                "date": date,
                "future_return": 0.03 if label else -0.01,
                "label": label,
                "score": float(20 + idx),
                "adx": 18.0 + label * 10,
                "rsi": 44.0 + label * 10,
                "volume_ratio": 1.0 + label * 0.4,
                "atr_pct": 0.02,
                "risk_reward_ratio": 2.0,
                "volatility_scale": 1.0,
                "correlation_scale": 1.0,
                "trend_bias": 1.0,
                "close_vs_ema_long": 0.01 + label * 0.03,
            }
        )
    model, _, _ = train_meta_model_from_dataset(
        pd.DataFrame(training_rows),
        split_config=SplitConfig(
            train_fraction=0.5, validation_fraction=0.2, calibration_fraction=0.1
        ),
        label_definition=LabelDefinition(horizon_bars=5, return_threshold=0.02),
        calibration_method="platt",
        output_dir=tmp_path,
    )

    ablation = Backtester(
        initial_capital=10000,
        indicators=IdentityIndicators(),
        meta_model=model,
        min_probability=0.5,
        fractional_kelly=0.25,
        max_position_cap_pct=20.0,
    ).run_ablation("TEST.IS", build_ablation_frame(), verbose=False)

    assert "meta_filter_fractional_kelly" in ablation.runs
