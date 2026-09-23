"""USD/TRY cezası + XU100 voter (market_context) birim ve entegrasyon testleri.

Varsayılan flag'ler KAPALI → mevcut davranış birebir korunur (parite).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.strategy import StrategyEngine
from bist_bot.strategy.market_context import (
    MarketContext,
    forex_penalty,
    usdtry_trend_rising,
)
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import MACRO_REGIME_MIN_BARS, MarketRegime


def _usdtry_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _rising_usdtry(n: int = 30) -> pd.DataFrame:
    return _usdtry_df([30.0 + i * 0.5 for i in range(n)])


def _flat_usdtry(n: int = 30) -> pd.DataFrame:
    return _usdtry_df([30.0] * n)


# ---------------------------------------------------------------------------
# usdtry_trend_rising
# ---------------------------------------------------------------------------


def test_usdtry_trend_rising_true_when_close_above_sma() -> None:
    assert usdtry_trend_rising(_rising_usdtry(), lookback=20) is True


def test_usdtry_trend_rising_false_when_flat() -> None:
    assert usdtry_trend_rising(_flat_usdtry(), lookback=20) is False


def test_usdtry_trend_rising_false_on_insufficient_history() -> None:
    assert usdtry_trend_rising(_usdtry_df([30.0, 31.0]), lookback=20) is False


def test_usdtry_trend_rising_false_on_missing_data() -> None:
    assert usdtry_trend_rising(None, lookback=20) is False
    assert usdtry_trend_rising(pd.DataFrame({"open": [1.0] * 30}), lookback=20) is False


# ---------------------------------------------------------------------------
# forex_penalty (saf fonksiyon)
# ---------------------------------------------------------------------------


def _params(**overrides: Any) -> StrategyParams:
    base: dict[str, Any] = {
        "forex_filter_enabled": True,
        "forex_penalty_points": 5.0,
        "forex_risk_sectors": ("HAVACILIK",),
        "forex_trend_lookback": 20,
    }
    base.update(overrides)
    return StrategyParams(**base)


def test_forex_penalty_disabled_flag_is_noop() -> None:
    points, reason = forex_penalty(
        params=_params(forex_filter_enabled=False),
        ticker="THYAO.IS",
        sector_map={"THYAO.IS": "HAVACILIK"},
        usdtry_df=_rising_usdtry(),
    )
    assert points == 0.0
    assert reason is None


def test_forex_penalty_applies_for_risk_sector_and_rising_usdtry() -> None:
    points, reason = forex_penalty(
        params=_params(),
        ticker="THYAO.IS",
        sector_map={"THYAO.IS": "HAVACILIK"},
        usdtry_df=_rising_usdtry(),
    )
    assert points == 5.0
    assert reason is not None and "USD/TRY" in reason


def test_forex_penalty_skips_non_risk_sector() -> None:
    points, reason = forex_penalty(
        params=_params(),
        ticker="GARAN.IS",
        sector_map={"GARAN.IS": "BANKA"},
        usdtry_df=_rising_usdtry(),
    )
    assert points == 0.0
    assert reason is None


def test_forex_penalty_noop_when_usdtry_not_rising_or_missing() -> None:
    for df in (_flat_usdtry(), None):
        points, reason = forex_penalty(
            params=_params(),
            ticker="THYAO.IS",
            sector_map={"THYAO.IS": "HAVACILIK"},
            usdtry_df=df,
        )
        assert points == 0.0
        assert reason is None


def test_forex_penalty_zero_points_is_noop() -> None:
    points, reason = forex_penalty(
        params=_params(forex_penalty_points=0.0),
        ticker="THYAO.IS",
        sector_map={"THYAO.IS": "HAVACILIK"},
        usdtry_df=_rising_usdtry(),
    )
    assert points == 0.0
    assert reason is None


# ---------------------------------------------------------------------------
# Parite: varsayılan parametrelerde makro filtreler kapalı
# ---------------------------------------------------------------------------


def test_default_params_parity_flags_off() -> None:
    params = StrategyParams()
    assert params.forex_filter_enabled is False
    assert params.xu100_voter_enabled is False
    assert params.forex_penalty_points == 5.0
    assert params.forex_risk_sectors == ("HAVACILIK",)


def test_validate_params_accepts_forex_defaults() -> None:
    assert _params().validate() == []
    assert StrategyParams().validate() == []


def test_validate_params_rejects_bad_forex_values() -> None:
    errors = _params(forex_penalty_points=-1.0).validate()
    assert any("forex_penalty_points" in e for e in errors)
    errors = _params(forex_trend_lookback=1).validate()
    assert any("forex_trend_lookback" in e for e in errors)


# ---------------------------------------------------------------------------
# Engine entegrasyonu: analyze() skoruna sabit ceza
# ---------------------------------------------------------------------------


class _IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


class _FakeRiskLevels:
    final_stop = 95.0
    final_target = 120.0
    confidence = "confidence.medium"
    risk_reward_ratio = 2.0
    method_used = "MarketContextTest"
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


class _FakeRiskManager:
    def calculate(self, df: pd.DataFrame) -> _FakeRiskLevels:
        return _FakeRiskLevels()

    def apply_portfolio_risk(self, ticker: str, df: pd.DataFrame, levels: Any) -> Any:
        return levels

    def reset_sectors(self) -> None: ...
    def reset_portfolio(self) -> None: ...
    def build_global_correlation_cache(self, data: object) -> None: ...
    def check_sector_limit(self, ticker: str) -> bool:
        return True

    def register_position(self, ticker: str, df: pd.DataFrame) -> None: ...


def _engine(params: StrategyParams) -> StrategyEngine:
    return StrategyEngine(
        indicators=cast(Any, _IdentityIndicators()),
        risk_manager=cast(Any, _FakeRiskManager()),
        params=params,
    )


def _bullish_frame(n: int = 60) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx in range(n):
        close = 100.0 + idx * 0.25
        rows.append(
            {
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 3000.0,
                "volume_sma_20": 1000.0,
                "adx": 30.0,
                "plus_di": 28.0,
                "minus_di": 12.0,
                f"ema_{settings.EMA_LONG}": 90.0,
                "rsi": 22.0,
                "stoch_k": 15.0,
                "stoch_d": 12.0,
                "stoch_cross": "BULLISH",
                "cci": -120.0,
                "sma_cross": "GOLDEN_CROSS",
                "ema_cross": "BULLISH",
                "macd_cross": "BULLISH",
                "macd_histogram": 1.0,
                "macd_hist_increasing": True,
                "di_cross": "BULLISH",
                "bb_position": "BELOW_LOWER",
                "bb_percent": 0.1,
                "bb_squeeze": False,
                "volume_spike": True,
                "volume_ratio": 3.0,
                "price_volume_direction": "BULLISH_CONFIRMATION",
                "price_volume_confirm": True,
                "volume_trend": "INCREASING",
                "obv_trend": "UP",
                "dist_to_support_pct": 1.0,
                "dist_to_resistance_pct": 20.0,
                "rsi_divergence": "BULLISH",
                "macd_divergence": "BULLISH",
                f"sma_{settings.SMA_FAST}": 102.0,
                f"sma_{settings.SMA_SLOW}": 98.0,
            }
        )
    return pd.DataFrame(rows)


def test_analyze_forex_penalty_reduces_long_score_by_fixed_points() -> None:
    frame = _bullish_frame()
    baseline = _engine(_params(forex_filter_enabled=False, session_adj_enabled=False)).analyze(
        "THYAO.IS", frame
    )
    assert baseline is not None

    engine = _engine(_params(forex_filter_enabled=True, session_adj_enabled=False))
    engine._market_context = MarketContext(usdtry_df=_rising_usdtry())
    penalized = engine.analyze("THYAO.IS", frame)

    assert penalized is not None
    assert penalized.score == baseline.score - 5.0
    assert any("USD/TRY" in r for r in penalized.reasons)


def test_analyze_forex_penalty_ignores_non_risk_sector() -> None:
    frame = _bullish_frame()
    engine = _engine(_params(forex_filter_enabled=True))
    engine._market_context = MarketContext(usdtry_df=_rising_usdtry())
    signal = engine.analyze("GARAN.IS", frame)
    assert signal is not None
    assert not any("USD/TRY" in r for r in signal.reasons)


def test_analyze_without_context_is_noop_even_when_enabled() -> None:
    frame = _bullish_frame()
    baseline = _engine(_params(forex_filter_enabled=False)).analyze("THYAO.IS", frame)
    engine = _engine(_params(forex_filter_enabled=True))  # market_context None
    signal = engine.analyze("THYAO.IS", frame)
    assert baseline is not None and signal is not None
    assert signal.score == baseline.score


# ---------------------------------------------------------------------------
# Faz 2: XU100 voter (macro regime gate)
# ---------------------------------------------------------------------------


def _benchmark_frame(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
        }
    )


def test_xu100_voter_included_only_when_enabled(monkeypatch: Any) -> None:
    captured: list[list[str]] = []

    def _fake_detect(dfs: dict[str, pd.DataFrame]) -> MarketRegime:
        captured.append(sorted(dfs.keys()))
        return MarketRegime.UNKNOWN

    monkeypatch.setattr("bist_bot.strategy.engine.detect_macro_regime", _fake_detect)

    off_engine = _engine(_params(xu100_voter_enabled=False))
    off_engine._market_context = MarketContext(xu100_df=_benchmark_frame())
    off_engine._detect_macro_regime({})
    assert captured[-1] == []

    on_engine = _engine(_params(xu100_voter_enabled=True))
    on_engine._market_context = MarketContext(xu100_df=_benchmark_frame())
    on_engine._detect_macro_regime({})
    assert captured[-1] == ["XU100.IS"]


def test_xu100_voter_skips_short_history(monkeypatch: Any) -> None:
    captured: list[list[str]] = []
    monkeypatch.setattr(
        "bist_bot.strategy.engine.detect_macro_regime",
        lambda dfs: captured.append(sorted(dfs.keys())) or MarketRegime.UNKNOWN,
    )
    engine = _engine(_params(xu100_voter_enabled=True))
    engine._market_context = MarketContext(xu100_df=_benchmark_frame(MACRO_REGIME_MIN_BARS - 1))
    engine._detect_macro_regime({})
    assert captured[-1] == []


# ---------------------------------------------------------------------------
# Scanner: tarama başına tek fetch + flag'ler kapalıyken no-op
# ---------------------------------------------------------------------------


class _StubFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_single(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        self.calls.append(ticker)
        return _benchmark_frame()


def test_scanner_market_context_none_when_flags_off() -> None:
    from bist_bot.scanner import ScanService

    svc = ScanService.__new__(ScanService)
    svc.settings = settings  # FOREX_FILTER_ENABLED / XU100_VOTER_ENABLED default False
    svc.fetcher = cast(Any, _StubFetcher())
    assert svc._build_market_context() is None
    assert svc.fetcher.calls == []


def test_scanner_market_context_fetches_once_per_enabled_flag() -> None:
    from bist_bot.scanner import ScanService

    svc = ScanService.__new__(ScanService)
    svc.settings = SimpleNamespace(
        FOREX_FILTER_ENABLED=True,
        XU100_VOTER_ENABLED=True,
        USDTRY_TICKER="USDTRY=X",
        XU100_TICKER="XU100.IS",
    )
    fetcher = _StubFetcher()
    svc.fetcher = cast(Any, fetcher)
    ctx = svc._build_market_context()
    assert ctx is not None
    assert ctx.usdtry_df is not None
    assert ctx.xu100_df is not None
    assert fetcher.calls == ["USDTRY=X", "XU100.IS"]


def test_scanner_market_context_graceful_on_fetch_failure() -> None:
    from bist_bot.scanner import ScanService

    class _Boom:
        def fetch_single(self, ticker: str, period: str, interval: str) -> None:
            raise RuntimeError("network down")

    svc = ScanService.__new__(ScanService)
    svc.settings = SimpleNamespace(
        FOREX_FILTER_ENABLED=True,
        XU100_VOTER_ENABLED=False,
        USDTRY_TICKER="USDTRY=X",
    )
    svc.fetcher = cast(Any, _Boom())
    ctx = svc._build_market_context()
    assert ctx is not None
    assert ctx.usdtry_df is None  # ceza yok, gate yok
