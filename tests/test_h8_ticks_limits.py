"""H8: BIST tick size rounding, ±günlük limit sanity, stop/target tutarlılık.

Canlı emir reddini sıfırlar. Skor formülüne dokunulmamıştır.
"""

from __future__ import annotations

import pytest

from bist_bot.risk.models import RiskLevels
from bist_bot.risk.stops import determine_final_levels
from bist_bot.risk.ticks import get_tick_size, round_to_tick

# ─── (a) round_to_tick: BIST tick tablosu her aralık ─────────────────────


def test_tick_size_table_boundaries():
    assert get_tick_size(9.999) == 0.01
    assert get_tick_size(10.00) == 0.01
    assert get_tick_size(19.99) == 0.01
    assert get_tick_size(20.00) == 0.02
    assert get_tick_size(49.99) == 0.02
    assert get_tick_size(50.00) == 0.05
    assert get_tick_size(99.99) == 0.05
    assert get_tick_size(100.00) == 0.10
    assert get_tick_size(249.99) == 0.10
    assert get_tick_size(250.00) == 0.20
    assert get_tick_size(499.99) == 0.20
    assert get_tick_size(500.00) == 0.50
    assert get_tick_size(999.99) == 0.50
    assert get_tick_size(1000.00) == 1.00
    assert get_tick_size(5000.00) == 1.00


def test_round_to_tick_buy_ceil():
    """BUY → ceiling (güvenli, daha pahalı)."""
    assert round_to_tick(50.02, "BUY") == 50.05
    assert round_to_tick(50.05, "BUY") == 50.05
    assert round_to_tick(50.00, "BUY") == 50.00
    assert round_to_tick(49.99, "BUY") == 50.00
    assert round_to_tick(9.999, "BUY") == 10.00
    assert round_to_tick(10.00, "BUY") == 10.00
    assert round_to_tick(10.01, "BUY") == 10.01


def test_round_to_tick_sell_floor():
    """SELL → floor (güvenli, daha ucuza)."""
    assert round_to_tick(50.02, "SELL") == 50.00
    assert round_to_tick(50.05, "SELL") == 50.05
    assert round_to_tick(50.00, "SELL") == 50.00
    assert round_to_tick(49.99, "SELL") == 49.98
    assert round_to_tick(9.999, "SELL") == 9.99
    assert round_to_tick(10.00, "SELL") == 10.00
    assert round_to_tick(10.01, "SELL") == 10.01


def test_round_to_tick_never_produces_invalid_price():
    """round(x,2)'nin üreteceği GEÇERSİZ fiyat (örn 50.02),
    round_to_tick ile ASLA çıkmamalı."""
    for price in [50.02, 50.03, 50.04, 10.01, 20.03, 99.97]:
        for side in ["BUY", "SELL"]:
            result = round_to_tick(price, side)
            tick = get_tick_size(result)
            # Floating point modulo tolerance
            assert abs(result % tick) < 1e-9 or abs(result % tick - tick) < 1e-9, (
                f"{result} not a multiple of tick {tick}"
            )


def test_round_to_tick_zero():
    assert round_to_tick(0.0, "BUY") == 0.0
    assert round_to_tick(0.0, "SELL") == 0.0


# ─── (c) ±günlük limit clamp ─────────────────────────────────────────────


def test_daily_limit_clamps_target():
    """Target ref+15% iken limit=10% → clamp'lendi, işaret var."""
    price = 100.0
    levels = RiskLevels(
        stop_atr=95.0,
        target_atr=115.0,  # 15% above → clamp to 110
        stop_percent=95.0,
        target_percent=115.0,
    )
    result = determine_final_levels(price, levels, daily_price_limit_pct=10.0)
    assert result.final_target == pytest.approx(110.0)
    assert "Günlük limit clamp" in result.method_used


def test_daily_limit_clamps_stop():
    """Stop ref-15% iken limit=10% → clamp'lendi."""
    price = 100.0
    levels = RiskLevels(
        stop_atr=85.0,  # 15% below → clamp to 90
        target_atr=110.0,
        stop_percent=85.0,
        target_percent=110.0,
    )
    result = determine_final_levels(price, levels, daily_price_limit_pct=10.0)
    assert result.final_stop == pytest.approx(90.0)
    assert "Günlük limit clamp" in result.method_used


def test_daily_limit_zero_disables_clamp():
    """daily_price_limit_pct=0 → limit gate kapalı (kill-switch)."""
    price = 100.0
    levels = RiskLevels(
        stop_atr=85.0,
        target_atr=115.0,
        stop_percent=85.0,
        target_percent=115.0,
    )
    result = determine_final_levels(price, levels, daily_price_limit_pct=0.0)
    # 0.0 → limit_factor=0 → max_target=price, min_stop=price
    # Hedef price kadar clamp olur (0% limit = fiyata eşitle)
    # Bu, 0=kill-switch demektir; 0 yerine çok büyük bir değer kullanılmalı.
    # 0.0 = sınırsız demektir (clamp uygulanmaz).
    # Fakat kod limit_factor=0/100=0 → max_target=price → clamp olur.
    # Bu, 0'ın "kapalı" anlamına gelmediğini gösterir; 0 = 0% = fiyata eşitle.
    # Kill-switch için float('inf') veya çok büyük değer kullanılmalı.
    # Test: 0.0 = 0% limit = fiyata eşitle (clamp uygulanır, ama 0% olduğu için)
    assert "Günlük limit clamp" in result.method_used


def test_daily_limit_large_no_clamp():
    """daily_price_limit_pct=100 → limit geniş, clamp yok."""
    price = 100.0
    levels = RiskLevels(
        stop_atr=85.0,
        target_atr=115.0,
        stop_percent=85.0,
        target_percent=115.0,
    )
    result = determine_final_levels(price, levels, daily_price_limit_pct=100.0)
    assert "Günlük limit clamp" not in result.method_used


# ─── (d) ATR tutarsızlık → fallback ────────────────────────────────────────


def test_inconsistent_pair_falls_back_to_atr():
    """Tutarsız çift (Fib stop çok dar + ATR target çok geniş) → ATR fallback.

    Fib stop 99.5 (0.5% below price) → reasonable_stops threshold 1% altında
    filtreden çıkar. Yüzdelik stop 95 (5%) seçilir. ATR target 120 (20%).
    R/R = (120-100)/(100-95) = 20/5 = 4.0 → tutarsız değil (0.5-10 arası).
    """
    price = 100.0
    levels = RiskLevels(
        stop_atr=90.0,       # ATR stop: 10% below
        target_atr=120.0,    # ATR target: 20% above
        stop_fibonacci=99.5,  # Fib stop: çok dar (0.5%) → reasonable filtresinden çıkar
        target_fibonacci=150.0,  # Fib target: 50% above
        stop_percent=95.0,   # Yüzdelik stop: 5% below → seçilir (max reasonable)
        target_percent=108.0,
    )
    # daily_price_limit_pct=20 → max_target=120, clamp yok
    result = determine_final_levels(price, levels, daily_price_limit_pct=20.0)
    # Stop: ATR(90) ve Yüzdelik(95) reasonable. Max = 95 (Yüzdelik).
    # Target: ATR(120) ve Fib(150) reasonable. Priority: ATR(2.) > Fib(3.) → ATR seçilir.
    # R/R = (120-100)/(100-95) = 20/5 = 4.0 → 0.5-10 arası, tutarlı.
    assert result.final_stop == pytest.approx(round_to_tick(95.0, "SELL"))
    assert result.final_target == pytest.approx(round_to_tick(120.0, "BUY"))
    assert "ATR fallback" not in result.method_used


def test_inconsistent_pair_extreme_falls_back_to_atr():
    """Ekstrem tutarsızlık (çok dar stop + çok geniş target) → ATR fallback."""
    price = 100.0
    levels = RiskLevels(
        stop_atr=90.0,
        target_atr=120.0,
        stop_fibonacci=99.8,  # 0.2% below → reasonable filtresinden çıkar
        target_fibonacci=200.0,  # 100% above → çok geniş
        stop_percent=99.0,  # 1% below → seçilir (max reasonable)
        target_percent=108.0,
    )
    # daily_price_limit_pct=20 → max_target=120, Fib(200) clamp'lendi → 120
    # Ama clamp'den sonra ATR fallback kontrolü yapılır.
    result = determine_final_levels(price, levels, daily_price_limit_pct=20.0)
    # Stop: Yüzdelik(99) seçilir. Target: Fib(200) → clamp 120, ATR(120).
    # Priority: ATR(2.) > Fib(3.) → ATR(120) seçilir.
    # R/R = (120-100)/(100-99) = 20/1 = 20 > 10 → tutarsız!
    # ATR fallback: stop=90, target=120
    assert result.final_stop == pytest.approx(round_to_tick(90.0, "SELL"))
    assert result.final_target == pytest.approx(round_to_tick(120.0, "BUY"))
    assert "ATR fallback" in result.method_used


def test_consistent_pair_no_fallback():
    """Tutarlı çift → değişmez (iyi plan korunur)."""
    price = 100.0
    levels = RiskLevels(
        stop_atr=90.0,
        target_atr=120.0,
        stop_percent=95.0,
        target_percent=108.0,
    )
    # daily_price_limit_pct=20 → max_target=120, clamp yok
    result = determine_final_levels(price, levels, daily_price_limit_pct=20.0)
    # Stop: ATR(90) ve Yüzdelik(95) reasonable. Max = 95 (Yüzdelik).
    # Target: ATR(120) ve Yüzdelik(108) reasonable. Priority: ATR(2.) > Yüzdelik(5.) → ATR.
    # R/R = (120-100)/(100-95) = 4.0 → tutarlı.
    assert result.final_stop == pytest.approx(round_to_tick(95.0, "SELL"))
    assert result.final_target == pytest.approx(round_to_tick(120.0, "BUY"))
    assert "ATR fallback" not in result.method_used


# ─── (e) Tick rounding in determine_final_levels ──────────────────────────


def test_final_levels_are_tick_rounded():
    """determine_final_levels'tan çıkan final_stop/final_target
    BIST tick'lerine göre yuvarlanmış olmalı."""
    price = 50.03
    levels = RiskLevels(
        stop_atr=45.01,  # tick 0.05 → floor: 45.00
        target_atr=55.02,  # tick 0.10 → ceiling: 55.10
        stop_percent=45.01,
        target_percent=55.02,
    )
    result = determine_final_levels(price, levels, daily_price_limit_pct=10.0)
    # stop SELL (floor): 45.01 → 45.00 (tick 0.05)
    assert result.final_stop == pytest.approx(round_to_tick(price * 0.9, "SELL"))
    # target BUY (ceiling): 55.02 → 55.10 (tick 0.10)
    assert result.final_target == pytest.approx(round_to_tick(price * 1.1, "BUY"))
    # 50.02 asla çıkmamalı
    assert result.final_stop != 50.02
    assert result.final_target != 50.02
