"""Content-keyed memo around TechnicalIndicators.add_all."""

from __future__ import annotations

import pandas as pd

from bist_bot.indicators import TechnicalIndicators, _clear_add_all_cache, cached_add_all


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


class TestCachedAddAll:
    def setup_method(self) -> None:
        _clear_add_all_cache()

    def teardown_method(self) -> None:
        _clear_add_all_cache()

    def test_same_content_returns_same_frame(self) -> None:
        df = _frame()
        first = cached_add_all(df.copy(), "TEST")
        second = cached_add_all(df.copy(), "TEST")
        assert first is second

    def test_different_ticker_misses_cache(self) -> None:
        df = _frame()
        a = cached_add_all(df.copy(), "AAA")
        b = cached_add_all(df.copy(), "BBB")
        assert a is not b

    def test_different_content_misses_cache(self) -> None:
        a = cached_add_all(_frame(40, 100.0), "TEST")
        b = cached_add_all(_frame(40, 101.0), "TEST")
        assert a is not b

    def test_mock_bypasses_cache(self) -> None:
        calls: list[int] = []

        class Spy:
            def add_all(self, frame: pd.DataFrame) -> pd.DataFrame:
                calls.append(len(frame))
                return frame

        df = _frame()
        spy = Spy()
        out1 = cached_add_all(df.copy(), "TEST", indicators=spy)
        out2 = cached_add_all(df.copy(), "TEST", indicators=spy)
        assert calls == [40, 40]
        assert out1 is not out2

    def test_real_indicators_hit_after_clear(self) -> None:
        df = _frame()
        ti = TechnicalIndicators()
        first = cached_add_all(df.copy(), "TEST", indicators=ti)
        second = cached_add_all(df.copy(), "TEST", indicators=ti)
        assert first is second
        _clear_add_all_cache()
        third = cached_add_all(df.copy(), "TEST", indicators=ti)
        assert third is not first
        assert list(third.columns) == list(first.columns)


class TestTrendBiasEnrichCache:
    def setup_method(self) -> None:
        from bist_bot.strategy.regime import _clear_trend_bias_enrich_cache

        _clear_trend_bias_enrich_cache()

    def teardown_method(self) -> None:
        from bist_bot.strategy.regime import _clear_trend_bias_enrich_cache

        _clear_trend_bias_enrich_cache()

    def test_warm_cache_skips_patched_add_atr(self, monkeypatch) -> None:
        """Second get_trend_bias on same content must not re-run add_atr."""
        from bist_bot.strategy.regime import get_trend_bias

        df = _frame(60)
        ti = TechnicalIndicators()
        first = get_trend_bias(ti, df.copy())

        calls: list[int] = []

        def boom(*_args, **_kwargs):
            calls.append(1)
            raise AssertionError("add_atr should not run on cache hit")

        monkeypatch.setattr(TechnicalIndicators, "add_atr", staticmethod(boom))
        second = get_trend_bias(ti, df.copy())
        assert second == first
        assert calls == []


class TestMacroBenchmarkEnrichCache:
    def setup_method(self) -> None:
        from bist_bot.strategy.engine import _clear_macro_benchmark_enrich_cache

        _clear_macro_benchmark_enrich_cache()

    def teardown_method(self) -> None:
        from bist_bot.strategy.engine import _clear_macro_benchmark_enrich_cache

        _clear_macro_benchmark_enrich_cache()

    def test_same_content_returns_same_frame(self) -> None:
        from bist_bot.strategy.engine import StrategyEngine

        df = _frame(60)
        e1 = StrategyEngine._enrich_macro_benchmark(df.copy())
        e2 = StrategyEngine._enrich_macro_benchmark(df.copy())
        assert e1 is e2

    def test_different_content_misses_cache(self) -> None:
        from bist_bot.strategy.engine import StrategyEngine

        e1 = StrategyEngine._enrich_macro_benchmark(_frame(60, 100.0))
        e2 = StrategyEngine._enrich_macro_benchmark(_frame(60, 101.0))
        assert e1 is not e2
