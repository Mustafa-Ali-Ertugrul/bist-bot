"""Cache-key correctness: settings fingerprint, thread locks, force-refresh clear."""

from __future__ import annotations

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.indicators import (
    TechnicalIndicators,
    _clear_add_all_cache,
    cached_add_all,
    clear_force_refresh_caches,
)


def _frame(n: int = 40, base: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = [base + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


class TestAddAllSettingsFingerprint:
    def setup_method(self) -> None:
        _clear_add_all_cache()

    def teardown_method(self) -> None:
        _clear_add_all_cache()

    def test_warm_then_settings_change_causes_miss(self) -> None:
        df = _frame()
        first = cached_add_all(df.copy(), "TEST")
        assert first is not None
        with settings.override(RSI_PERIOD=21):
            second = cached_add_all(df.copy(), "TEST")
        assert second is not None
        assert second is not first

    def test_same_override_returns_hit(self) -> None:
        df = _frame()
        with settings.override(RSI_PERIOD=21):
            first = cached_add_all(df.copy(), "TEST")
            second = cached_add_all(df.copy(), "TEST")
        assert first is second


class TestTrendBiasSettingsFingerprint:
    def setup_method(self) -> None:
        from bist_bot.strategy.regime import _clear_trend_bias_enrich_cache

        _clear_trend_bias_enrich_cache()

    def teardown_method(self) -> None:
        from bist_bot.strategy.regime import _clear_trend_bias_enrich_cache

        _clear_trend_bias_enrich_cache()

    def test_warm_then_settings_change_causes_miss(self, monkeypatch) -> None:
        """Changing ATR_PERIOD must cause a recompute on the next call."""
        from bist_bot.strategy.regime import get_trend_bias

        df = _frame(60)
        ti = TechnicalIndicators()
        _ = get_trend_bias(ti, df.copy())

        # Spy that counts calls but delegates to the ORIGINAL add_atr. With
        # settings changed the content key gains a different fingerprint →
        # miss → add_atr must run at least once inside the override.
        original_add_atr = TechnicalIndicators.add_atr
        calls: list[int] = []

        def counting_add_atr(*args, **kwargs):
            calls.append(1)
            return original_add_atr(*args, **kwargs)

        monkeypatch.setattr(TechnicalIndicators, "add_atr", staticmethod(counting_add_atr))
        with settings.override(ATR_PERIOD=21):
            second = get_trend_bias(ti, df.copy())
        assert second is not None
        assert calls, "settings change must invalidate the trend-bias enrich cache"

    def test_restored_settings_hits_cache(self, monkeypatch) -> None:
        from bist_bot.strategy.regime import get_trend_bias

        df = _frame(60)
        ti = TechnicalIndicators()
        first = get_trend_bias(ti, df.copy())

        # Install a spy that tracks calls but delegates to the ORIGINAL method.
        original_add_atr = TechnicalIndicators.add_atr
        calls: list[int] = []

        def counting_add_atr(*args, **kwargs):
            calls.append(1)
            return original_add_atr(*args, **kwargs)

        monkeypatch.setattr(TechnicalIndicators, "add_atr", staticmethod(counting_add_atr))
        # Settings are at their defaults again — should be a cache hit, no add_atr call.
        result = get_trend_bias(ti, df.copy())
        assert result is not None
        assert result == first
        assert calls == []


class TestMacroBenchmarkSettingsFingerprint:
    def setup_method(self) -> None:
        from bist_bot.strategy.engine import _clear_macro_benchmark_enrich_cache

        _clear_macro_benchmark_enrich_cache()

    def teardown_method(self) -> None:
        from bist_bot.strategy.engine import _clear_macro_benchmark_enrich_cache

        _clear_macro_benchmark_enrich_cache()

    def test_warm_then_settings_change_causes_miss(self, monkeypatch) -> None:
        from bist_bot.strategy.engine import StrategyEngine

        df = _frame(60)
        _ = StrategyEngine._enrich_macro_benchmark(df.copy())

        original_add_atr = TechnicalIndicators.add_atr
        calls: list[int] = []

        def counting_add_atr(*args, **kwargs):
            calls.append(1)
            return original_add_atr(*args, **kwargs)

        monkeypatch.setattr(TechnicalIndicators, "add_atr", staticmethod(counting_add_atr))
        with settings.override(ATR_PERIOD=21):
            second = StrategyEngine._enrich_macro_benchmark(df.copy())
        assert second is not None
        assert calls, "settings change must invalidate the macro-benchmark enrich cache"

    def test_restored_settings_hits_cache(self, monkeypatch) -> None:
        from bist_bot.strategy.engine import StrategyEngine

        df = _frame(60)
        _ = StrategyEngine._enrich_macro_benchmark(df.copy())

        original_add_atr = TechnicalIndicators.add_atr
        calls: list[int] = []

        def counting_add_atr(*args, **kwargs):
            calls.append(1)
            return original_add_atr(*args, **kwargs)

        monkeypatch.setattr(TechnicalIndicators, "add_atr", staticmethod(counting_add_atr))
        _ = StrategyEngine._enrich_macro_benchmark(df.copy())
        assert calls == []


class TestWhaleCacheSettingsFingerprint:
    def setup_method(self) -> None:
        from bist_bot.services.whale_alert_service import _clear_whale_indicators_cache

        _clear_whale_indicators_cache()

    def teardown_method(self) -> None:
        from bist_bot.services.whale_alert_service import _clear_whale_indicators_cache

        _clear_whale_indicators_cache()

    def test_warm_then_settings_change_causes_miss(self) -> None:
        from bist_bot.services.whale_alert_service import _cached_add_all

        df = _frame()
        first = _cached_add_all(df.copy(), "TEST")
        assert first is not None
        with settings.override(RSI_PERIOD=21):
            second = _cached_add_all(df.copy(), "TEST")
        assert second is not None
        assert second is not first


class TestClearForceRefreshCaches:
    def teardown_method(self) -> None:
        clear_force_refresh_caches()

    def test_clears_all_four_caches(self, monkeypatch) -> None:
        from bist_bot.services.whale_alert_service import _cached_add_all as whale_cached
        from bist_bot.strategy.engine import StrategyEngine
        from bist_bot.strategy.regime import get_trend_bias

        df = _frame(60)
        ti = TechnicalIndicators()

        first_add = cached_add_all(df.copy(), "T1")
        first_regime = get_trend_bias(ti, df.copy())
        first_macro = StrategyEngine._enrich_macro_benchmark(df.copy())
        first_whale = whale_cached(df.copy(), "T1")

        assert first_add is not None
        assert first_regime is not None
        assert first_macro is not None
        assert first_whale is not None

        clear_force_refresh_caches()

        # get_trend_bias returns a TrendBias enum member, so identity checks
        # cannot detect a hit/miss — spy on add_atr instead: after the clear
        # the enrich path must recompute (spy fires), proving the clear worked.
        original_add_atr = TechnicalIndicators.add_atr
        calls: list[int] = []

        def counting_add_atr(*args, **kwargs):
            calls.append(1)
            return original_add_atr(*args, **kwargs)

        monkeypatch.setattr(TechnicalIndicators, "add_atr", staticmethod(counting_add_atr))

        second_add = cached_add_all(df.copy(), "T1")
        second_regime = get_trend_bias(ti, df.copy())
        second_macro = StrategyEngine._enrich_macro_benchmark(df.copy())
        second_whale = whale_cached(df.copy(), "T1")

        assert second_add is not first_add
        assert second_regime == first_regime  # same logical result, recomputed
        assert second_macro is not first_macro
        assert second_whale is not first_whale
        assert calls, "clear_force_refresh_caches must empty the trend-bias cache"


class TestScannerForceRefreshInvokesClear:
    def test_scan_once_force_refresh_calls_clear_helper(self, monkeypatch) -> None:
        """scan_once(force_refresh=True) must call clear_force_refresh_caches()."""
        from unittest.mock import MagicMock, patch

        from bist_bot.scanner import ScanService
        from bist_bot.strategy.signal_models import Signal, SignalType

        fetcher = MagicMock()
        fetcher.fetch_multi_timeframe_all.return_value = {
            "THYAO.IS": {"trigger": object(), "trend": object()}
        }
        engine = MagicMock()
        notifier = MagicMock()
        db = MagicMock()
        db.get_latest_signal.return_value = None
        engine.get_last_rejection_breakdown.return_value = {
            "total_rejections": 0,
            "by_reason": [],
            "by_stage": [],
            "scan_id": "scan-force",
        }
        signal = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25, price=100.0)
        engine.scan_all.return_value = [signal]
        engine.get_actionable_signals.return_value = [signal]

        with patch("bist_bot.scanner.clear_force_refresh_caches") as mock_clear:
            service = ScanService(fetcher, engine, notifier, db)
            service.scan_once(force_refresh=True)
            mock_clear.assert_called_once_with()

        fetcher.fetch_multi_timeframe_all.assert_called_once()
        assert fetcher.fetch_multi_timeframe_all.call_args.kwargs["force_refresh"] is True
