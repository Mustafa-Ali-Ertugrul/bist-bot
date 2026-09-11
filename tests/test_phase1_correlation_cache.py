"""Aşama 2: bağlam-anahtarlı günlük korelasyon memo testleri.

Kabul kriterleri (düzeltilmiş plan Adım 2):
- Aynı gün/bağlam: hesap fonksiyonu bir kez çağrılır, snapshot eşleşir.
- Tarih/evren/konfigürasyon/bağlam değişimi: yeniden hesaplanır.
- reset_portfolio() memo'yu silmez (her scan'de çağrıldığı için; aksi halde
  cache hiç vurmazdı — §1.7 çözümü), canlı cache'i sıfırlar (mevcut davranış).
- Başarısız/boş hesap memo'lanmaz.
- Backtest tarihi sistem tarihinden bağımsızdır.
- get_correlation_matrix() her çağrıda mevcut hesap yolunu kullanır.
"""

from datetime import date

import numpy as np
import pandas as pd

from bist_bot.risk import correlation as corr_module
from bist_bot.risk.manager import RiskManager


def _universe(n: int = 60, seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    base = 100 + np.cumsum(rng.normal(0.2, 1.0, n))
    return {
        "AAA.IS": pd.DataFrame({"close": base}),
        "BBB.IS": pd.DataFrame({"close": base * 1.5 + 3.0}),
        "CCC.IS": pd.DataFrame({"close": 100 + np.cumsum(rng.normal(0.0, 2.0, n))}),
    }


def _counting_manager(monkeypatch) -> tuple[RiskManager, dict]:
    calls = {"n": 0}
    real = corr_module.build_global_correlation_cache

    def _wrapper(data):
        calls["n"] += 1
        return real(data)

    monkeypatch.setattr(corr_module, "build_global_correlation_cache", _wrapper)
    return RiskManager(capital=10_000.0), calls


def test_same_day_context_builds_once(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    data = _universe()
    day = date(2026, 9, 10)
    manager.build_global_correlation_cache(data, session_date=day)
    first = manager._global_corr_cache
    assert first is not None
    manager.build_global_correlation_cache(data, session_date=day)
    assert calls["n"] == 1
    pd.testing.assert_frame_equal(manager._global_corr_cache, first)


def test_memo_result_matches_fresh_compute(monkeypatch) -> None:
    manager, _ = _counting_manager(monkeypatch)
    data = _universe()
    day = date(2026, 9, 10)
    manager.build_global_correlation_cache(data, session_date=day)
    fresh = corr_module.build_global_correlation_cache(data)
    pd.testing.assert_frame_equal(manager._global_corr_cache, fresh)


def test_next_day_recomputes(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    data = _universe()
    manager.build_global_correlation_cache(data, session_date=date(2026, 9, 10))
    manager.build_global_correlation_cache(data, session_date=date(2026, 9, 11))
    assert calls["n"] == 2


def test_universe_change_recomputes(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    day = date(2026, 9, 10)
    manager.build_global_correlation_cache(_universe(), session_date=day)
    grown = _universe()
    grown["DDD.IS"] = pd.DataFrame(
        {"close": 50 + np.cumsum(np.random.default_rng(9).normal(0.1, 1.0, 60))}
    )
    manager.build_global_correlation_cache(grown, session_date=day)
    assert calls["n"] == 2
    assert manager._global_corr_cache is not None
    assert manager._global_corr_cache.shape == (4, 4)


def test_config_change_recomputes(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    data = _universe()
    day = date(2026, 9, 10)
    manager.build_global_correlation_cache(data, session_date=day)
    manager.correlation_threshold = 0.99
    manager.build_global_correlation_cache(data, session_date=day)
    assert calls["n"] == 2


def test_context_change_recomputes(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    data = _universe()
    day = date(2026, 9, 10)
    manager.build_global_correlation_cache(data, session_date=day, data_context="live")
    manager.build_global_correlation_cache(data, session_date=day, data_context="backtest")
    assert calls["n"] == 2


def test_reset_keeps_memo_but_clears_live_cache(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    data = _universe()
    day = date(2026, 9, 10)
    manager.build_global_correlation_cache(data, session_date=day)
    manager.reset_portfolio()
    assert manager._global_corr_cache is None  # mevcut davranış korunur
    manager.build_global_correlation_cache(data, session_date=day)
    assert calls["n"] == 1  # memo restore, yeniden hesap yok
    assert manager._global_corr_cache is not None


def test_failed_build_is_not_memoized(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    day = date(2026, 9, 10)
    data = _universe()
    # Önce başarısız hesap: boş frameler -> None, memo'ya yazılmaz.
    empty = {t: pd.DataFrame({"close": pd.Series(dtype=float)}) for t in data}
    manager.build_global_correlation_cache(empty, session_date=day)
    assert calls["n"] == 1
    assert manager._global_corr_cache is None
    assert manager._corr_memo_key is None
    # Gerçek veri aynı anahtarla gelince hesaplanır ve memo'lanır.
    manager.build_global_correlation_cache(data, session_date=day)
    assert calls["n"] == 2
    assert manager._global_corr_cache is not None
    # Tekrarı memo'dan gelir.
    manager.build_global_correlation_cache(data, session_date=day)
    assert calls["n"] == 2


def test_backtest_asof_date_independent_of_system_date(monkeypatch) -> None:
    manager, calls = _counting_manager(monkeypatch)
    data = _universe()
    asof = date(2020, 1, 15)
    manager.build_global_correlation_cache(data, session_date=asof, data_context="backtest")
    manager.build_global_correlation_cache(data, session_date=asof, data_context="backtest")
    assert calls["n"] == 1
    assert manager._corr_memo_key is not None
    assert manager._corr_memo_key[0] == asof


def test_get_correlation_matrix_still_computes_fresh() -> None:
    manager = RiskManager(capital=10_000.0)
    data = _universe()
    manager.register_position("AAA.IS", data["AAA.IS"])
    manager.register_position("BBB.IS", data["BBB.IS"])
    first = manager.get_correlation_matrix()
    second = manager.get_correlation_matrix()
    pd.testing.assert_frame_equal(first, second)
    assert round(float(first.loc["AAA.IS", "BBB.IS"]), 6) == 1.0
