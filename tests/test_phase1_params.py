"""Aşama 1: parametreleştirme reach + öncelik + validasyon testleri.

Her yeni env ayarının tüketiciye ulaştığı, override önceliğinin korunduğu
(profil explicit > env) ve geçersiz değerlerin preflight'ta yakalandığı
kanıtlanır. Env override yokken davranışın değişmediği ise
``test_phase1_reference.py`` golden'ları ile korunur.
"""

import numpy as np
import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.risk import correlation as corr
from bist_bot.risk.manager import RiskManager
from bist_bot.strategy import engine as engine_module
from bist_bot.strategy.engine import StrategyEngine
from bist_bot.strategy.engine_filters import calculate_score_and_reasons, classify_signal
from bist_bot.strategy.params import StrategyParams, validate_strategy_params
from bist_bot.strategy.regime import (
    MarketRegime,
    benchmark_regime_series,
    detect_regime,
    get_trend_bias,
)
from bist_bot.strategy.scoring import score_momentum, score_structure, score_trend
from bist_bot.strategy.signal_models import SignalCategory, SignalType, categorize

# ----------------------------------------------------------------------
# Env -> params -> tüketici reach
# ----------------------------------------------------------------------


def test_rsi_env_reaches_params() -> None:
    with settings.override(RSI_OVERSOLD=25, RSI_OVERBOUGHT=75):
        p = StrategyParams()
    assert p.rsi_oversold == 25.0
    assert p.rsi_overbought == 75.0


def test_from_settings_carries_rsi_for_every_profile() -> None:
    with settings.override(RSI_OVERSOLD=25, STRATEGY_PROFILE="conservative"):
        assert StrategyParams.from_settings().rsi_oversold == 25.0
    with settings.override(RSI_OVERSOLD=25, STRATEGY_PROFILE="champion"):
        assert StrategyParams.from_settings().rsi_oversold == 25.0


def test_profile_explicit_wins_over_env_documented() -> None:
    """De-facto öncelik: profil explicit değeri env'i ezer.

    ``conservative()`` adx_threshold'u 20.0 pinler; bu, env ADX_THRESHOLD'u
    o profilde etkisiz kılar. Sırayı değiştirmek davranış değişikliğidir
    (ayrı karar gerekir); burada yalnızca sabitlenir.
    """
    with settings.override(ADX_THRESHOLD=99):
        assert StrategyParams.conservative().adx_threshold == 20.0
        # Profilin değmediği alanlarda env geçerlidir.
        assert StrategyParams.conservative().rsi_oversold == float(settings.RSI_OVERSOLD)


def test_max_signal_score_env_reaches_categorize() -> None:
    with settings.override(MAX_SIGNAL_SCORE=40.0):
        assert categorize(SignalType.BUY, 50.0, 35.0) == SignalCategory.AL
    with settings.override(MAX_SIGNAL_SCORE=33.0):
        assert categorize(SignalType.BUY, 50.0, 35.0) == SignalCategory.RADAR


def test_momentum_cap_env_reaches_clamp() -> None:
    last = pd.Series(
        {"rsi": 20.0, "stoch_k": 15.0, "stoch_d": 12.0, "stoch_cross": "BULLISH", "cci": -120.0}
    )
    with settings.override(MOMENTUM_SCORE_CAP=10.0):
        score, _ = score_momentum(StrategyParams(), last, pd.Series())
    assert score == 10.0


def test_stoch_oversold_env_reaches_scorer() -> None:
    last = pd.Series(
        {"rsi": 50.0, "stoch_k": 15.0, "stoch_d": 15.0, "stoch_cross": "NONE", "cci": 0.0}
    )
    base, _ = score_momentum(StrategyParams(), last, pd.Series())
    assert base == 6.0  # score_stoch_extreme default
    with settings.override(STOCH_OVERSOLD=10.0):
        narrowed, _ = score_momentum(StrategyParams(), last, pd.Series())
    assert narrowed == 0.0


def test_cci_band_env_reaches_scorer() -> None:
    last = pd.Series(
        {"rsi": 50.0, "stoch_k": 50.0, "stoch_d": 50.0, "stoch_cross": "NONE", "cci": -60.0}
    )
    base, _ = score_momentum(StrategyParams(), last, pd.Series())
    assert base == 4.0  # score_cci_normal default
    with settings.override(CCI_MIN=-70.0):
        narrowed, _ = score_momentum(StrategyParams(), last, pd.Series())
    assert narrowed == 0.0


def test_bb_pct_band_env_reaches_scorer() -> None:
    last = pd.Series({"bb_position": "MIDDLE", "bb_percent": 0.15})
    base, _ = score_structure(StrategyParams(), last)
    assert base == 5.0  # score_bollinger_percent default
    with settings.override(BB_PCT_LOW=0.10):
        narrowed, _ = score_structure(StrategyParams(), last)
    assert narrowed == 0.0


def test_adx_strong_edge_env_reaches_scorer() -> None:
    last = pd.Series({"adx": 26.0, "plus_di": 20.0, "minus_di": 10.0})
    base, _ = score_trend(StrategyParams(), last, pd.Series())
    assert base == 8.0  # score_adx_strong default
    with settings.override(ADX_STRONG_EDGE=30.0):
        weakened, _ = score_trend(StrategyParams(), last, pd.Series())
    assert weakened == 3.0  # score_adx_weak default


def test_sr_distance_env_reaches_scorer() -> None:
    last = pd.Series(
        {
            "bb_position": "MIDDLE",
            "bb_percent": 0.5,
            "dist_to_support_pct": 1.0,
            "dist_to_resistance_pct": 50.0,
        }
    )
    base, _ = score_structure(StrategyParams(), last)
    assert base == 6.0  # score_sr_distance default
    with settings.override(SR_DISTANCE_PCT=0.5):
        narrowed, _ = score_structure(StrategyParams(), last)
    assert narrowed == 0.0


def test_agreement_bands_env_reach_classify() -> None:
    _, high = classify_signal(StrategyParams(), score=50.0, agreement_ratio=0.8)
    assert high == "confidence.high"
    with settings.override(AGREEMENT_FULL=0.9):
        _, lowered = classify_signal(StrategyParams(), score=50.0, agreement_ratio=0.8)
    assert lowered == "confidence.medium"


def test_agreement_divisor_env_reaches_pipeline() -> None:
    closes = np.linspace(100.0, 130.0, 60)
    df = pd.DataFrame(
        {
            "close": closes,
            "adx": np.full(60, 28.0),
            "plus_di": np.full(60, 30.0),
            "minus_di": np.full(60, 15.0),
        }
    )
    stub = lambda _l, _p, *_a: (10.0, [])  # noqa: E731
    kwargs = dict(
        momentum_scorer=stub,
        trend_scorer=lambda _l, _p, _d=None: (10.0, []),
        volume_scorer=stub,
        structure_scorer=lambda _l: (-5.0, []),
        momentum_checker=lambda _d, _t: True,
    )
    out = calculate_score_and_reasons(
        StrategyParams(), "T.IS", df, last=df.iloc[-1], prev=df.iloc[-2], **kwargs
    )
    assert out is not None
    assert out[2] == pytest.approx(0.75)  # 3/4 bileşen agree
    with settings.override(AGREEMENT_DIVISOR=2.0):
        out2 = calculate_score_and_reasons(
            StrategyParams(), "T.IS", df, last=df.iloc[-1], prev=df.iloc[-2], **kwargs
        )
    assert out2 is not None
    assert out2[2] == pytest.approx(1.5)


def _bull_frame(n: int = 60) -> pd.DataFrame:
    closes = np.linspace(100.0, 160.0, n)
    return pd.DataFrame(
        {
            "close": closes,
            "adx": np.full(n, 28.0),
            "plus_di": np.full(n, 30.0),
            "minus_di": np.full(n, 15.0),
        }
    )


def test_regime_di_ratio_env_reaches_detector() -> None:
    assert detect_regime(_bull_frame()) is MarketRegime.BULL
    with settings.override(REGIME_DI_RATIO=5.0):
        assert detect_regime(_bull_frame()) is MarketRegime.SIDEWAYS


def test_regime_min_bars_env_reaches_detector() -> None:
    assert detect_regime(_bull_frame()) is MarketRegime.BULL
    with settings.override(REGIME_MIN_BARS=61):
        assert detect_regime(_bull_frame()) is MarketRegime.UNKNOWN


def test_regime_vectorized_matches_scalar_under_override() -> None:
    frame = _bull_frame()
    with settings.override(REGIME_DI_RATIO=5.0):
        series = benchmark_regime_series(frame)
        assert set(series.iloc[49:]) == {MarketRegime.SIDEWAYS}
        assert detect_regime(frame) is series.iloc[-1]


def test_engine_passes_params_to_trend_bias(monkeypatch) -> None:
    seen: dict = {}

    def _spy(indicators, df, params=None):
        seen["params"] = params
        return MarketRegime.BULL  # type: ignore[return-value]

    monkeypatch.setattr(engine_module, "get_trend_bias", _spy)
    engine = StrategyEngine()
    engine._get_trend_bias(pd.DataFrame({"close": [1.0, 2.0]}))
    assert seen["params"] is engine.params


def test_get_trend_bias_params_flag_reaches_h6_gate() -> None:
    # get_trend_bias, indicators üzerinden ham OHLCV'yi zenginleştirir;
    # settings yolu (params=None) mevcut davranıştır.
    closes = np.concatenate([np.linspace(120.0, 100.0, 50), np.linspace(100.0, 108.0, 15)])
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": np.full(len(closes), 1000.0),
        }
    )
    ti = TechnicalIndicators()
    assert get_trend_bias(ti, df) == get_trend_bias(ti, df, StrategyParams())


def test_stoch_oversold_env_reaches_indicator_columns() -> None:
    n = 30
    closes = np.linspace(100.0, 130.0, n)
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )
    warm = slice(15, None)  # k(14) + d(3) warm-up sonrası
    default_out = TechnicalIndicators.add_stochastic(df)
    assert not bool(default_out["stoch_oversold"].iloc[warm].any())
    with settings.override(STOCH_OVERSOLD=100.0):
        out = TechnicalIndicators.add_stochastic(df)
    assert bool(out["stoch_oversold"].iloc[warm].all())


def test_obv_sma_period_env_reaches_indicator() -> None:
    n = 5
    df = pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": np.full(n, 101.0),
            "low": np.full(n, 99.0),
            "close": np.arange(100.0, 100.0 + n),
            "volume": np.full(n, 1000.0),
        }
    )
    default_out = TechnicalIndicators.add_obv(df)
    assert int(default_out["obv_sma"].notna().sum()) == 0  # rolling(20)
    with settings.override(OBV_SMA_PERIOD=3):
        out = TechnicalIndicators.add_obv(df)
    assert int(out["obv_sma"].notna().sum()) == 3


def test_corr_min_bars_env_reaches_manager() -> None:
    with settings.override(CORR_FALLBACK_MIN_BARS=11):
        manager = RiskManager(capital=10_000.0)
    assert manager.corr_fallback_min_bars == 11


def test_corr_min_bars_arg_preserved_at_call_site() -> None:
    n = 10
    closes = 100 + np.cumsum(np.random.default_rng(3).normal(0.2, 1.0, n))
    a = pd.DataFrame({"close": closes})
    b = pd.DataFrame({"close": closes * 1.5 + 3.0})
    assert corr.get_correlated_positions("A.IS", a, {"B.IS": b}, None, 0.70) == ["B.IS"]
    assert corr.get_correlated_positions("A.IS", a, {"B.IS": b}, None, 0.70, min_bars=11) == []


# ----------------------------------------------------------------------
# Validasyon
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"STOCH_K_PERIOD": 0}, "STOCH_K_PERIOD"),
        ({"STOCH_OVERSOLD": 80.0, "STOCH_OVERBOUGHT": 20.0}, "stoch_oversold < stoch_overbought"),
        ({"STOCH_TREND_MID": 150.0}, "stoch_trend_mid"),
        ({"CCI_MIN": 50.0, "CCI_MAX": -50.0}, "cci_min < cci_max"),
        ({"BB_PCT_LOW": 0.8, "BB_PCT_HIGH": 0.2}, "bb_pct_low < bb_pct_high"),
        ({"AGREEMENT_MIN": 0.9, "AGREEMENT_FULL": 0.1}, "agreement_min <= agreement_full"),
        ({"AGREEMENT_DIVISOR": 0.0}, "agreement_divisor pozitif"),
        ({"MOMENTUM_SCORE_CAP": -1.0}, "momentum_score_cap negatif"),
        ({"REGIME_MIN_BARS": 0}, "regime_min_bars"),
        (
            {"REGIME_TREND_ADX": 10.0, "REGIME_WEAK_ADX": 20.0},
            "regime_trend_adx >= regime_weak_adx",
        ),
        ({"REGIME_DI_RATIO": 0.0}, "regime_di_ratio pozitif"),
        ({"CORR_FALLBACK_MIN_BARS": 1}, "corr_fallback_min_bars >= 2"),
        ({"MAX_SIGNAL_SCORE": -5.0}, "MAX_SIGNAL_SCORE negatif"),
        ({"STOCH_OVERSOLD": float("nan")}, "sonlu sayı"),
    ],
)
def test_preflight_rejects_invalid_tunable(overrides, fragment) -> None:
    with settings.override(**overrides):
        errors = settings.collect_preflight_errors()
    assert any(fragment in e for e in errors), errors


def test_validate_shared_rules_for_direct_instances() -> None:
    assert StrategyParams().validate() == []
    assert validate_strategy_params(StrategyParams()) == []
    bad = StrategyParams(
        stoch_oversold=90.0, stoch_overbought=10.0, agreement_divisor=0.0, corr_fallback_min_bars=1
    )
    errors = bad.validate()
    assert any("stoch_oversold < stoch_overbought" in e for e in errors)
    assert any("agreement_divisor pozitif" in e for e in errors)
    assert any("corr_fallback_min_bars >= 2" in e for e in errors)
