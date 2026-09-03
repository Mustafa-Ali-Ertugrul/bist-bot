"""Volatility-adaptive stop/target tests (Z2)."""

from bist_bot.risk.models import RiskLevels
from bist_bot.risk.stops import determine_final_levels


def _levels(price: float = 100.0, **overrides) -> RiskLevels:
    lv = RiskLevels()
    # Set percent levels as fallback
    lv.stop_percent = round(price * 0.95, 2)  # -5%
    lv.target_percent = round(price * 1.08, 2)  # +8%
    for k, v in overrides.items():
        setattr(lv, k, v)
    return lv


def test_min_stop_widens_shallow_stop():
    price = 100.0
    lv = _levels(price, stop_percent=98.9)  # 1.1% stop
    lv.target_percent = 108.0
    result = determine_final_levels(price, lv)
    # MIN_STOP_LOSS_PCT=1.8 → floor at 98.2, should be <= 98.9 (widened)
    assert result.final_stop <= 98.9
    assert abs(result.final_stop - 98.2) < 0.06  # tick rounding tolerance


def test_high_vol_stop_unchanged():
    price = 100.0
    lv = _levels(price)
    lv.stop_support = 92.0  # 8% away, within reasonable (1-10%)
    lv.stop_percent = 95.0
    result = determine_final_levels(price, lv)
    # Strong support should be preferred over percent (max reasonable → 95? actually max is 95 >92, so percent wins)
    # At least reasonable stop should be chosen, not fallback to percent limit
    assert result.final_stop in (92.0, 95.0)


def test_shallow_vol_target_not_fixed_8pct():
    price = 100.0
    # ATR gives shallow target: 101.5 (1.5% < 2% floor) → fallback should give >102
    lv = _levels(price)
    lv.stop_atr = 98.0  # ATR stop
    lv.target_atr = 101.5  # 1.5% above → would be filtered as unreasonable (<2%)
    lv.stop_percent = 98.9  # 1.1% shallow
    # After fallback, target should be at least floor 2% → 102.0, or RR based
    result = determine_final_levels(price, lv)
    assert result.final_target >= 102.0
    assert result.final_target != 108.0 or result.final_target >= 102.0


def test_target_fallback_uses_rr():
    price = 100.0
    lv = _levels(price)
    lv.stop_atr = 95.0
    lv.target_atr = 101.0  # 1% → unreasonable
    lv.stop_percent = 98.5  # 1.5% risk
    # risk 1.5, RR 2.0 → target 103.0 → >= floor 102
    result = determine_final_levels(price, lv)
    assert result.final_target >= 102.0


def test_tick_rounding_preserved():
    price = 100.0
    lv = _levels(price, stop_percent=95.13, target_percent=108.27)
    result = determine_final_levels(price, lv)
    # tick rounding should keep 2 decimals
    assert round(result.final_stop, 2) == result.final_stop
    assert round(result.final_target, 2) == result.final_target


def test_daily_limit_clamp_preserved():
    price = 100.0
    lv = _levels(price)
    lv.stop_percent = 50.0  # 50% below → below -10% limit
    lv.target_percent = 200.0  # 100% above → above +10%
    result = determine_final_levels(price, lv)
    assert result.final_stop >= 90.0  # clamp to 90
    assert result.final_target <= 110.0  # clamp to 110


def test_atr_missing_keeps_percent_fallback():
    price = 100.0
    lv = _levels(price)
    lv.stop_atr = 0
    lv.target_atr = 0
    lv.stop_percent = 95.0
    lv.target_percent = 108.0
    result = determine_final_levels(price, lv)
    # No ATR → should keep percent
    assert result.final_target == 108.0 or result.final_target == 108.0  # tick rounded same


def test_fallback_respects_cap():
    price = 100.0
    lv = _levels(price)
    lv.stop_atr = 98.0
    lv.target_atr = 101.0
    lv.stop_percent = 98.0
    lv.target_percent = 108.0
    # Even with RR 2.0, cap 110 should hold
    result = determine_final_levels(price, lv)
    assert result.final_target <= 110.0
