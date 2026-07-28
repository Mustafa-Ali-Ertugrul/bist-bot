"""End-to-end integration and regression tests for ``RiskManager``.

WARNING / UYARI
---------------
If you intentionally change risk parameters (``MAX_POSITION_CAP_PCT``,
``MAX_TOTAL_RISK_PCT`` / ``max_risk_pct``, ``DAILY_LOSS_CAP_PCT``,
``MAX_SECTOR_CAP_PCT``, correlation thresholds, ATR throttle, or Kelly gates),
or the order of sizing → portfolio risk → probability sizing, you MUST
consciously update the expected position sizes, block flags, and sector-limit
behavior asserted in this file.

Bu dosya, strateji sinyallerinin sermayeyi koruyacak şekilde boyutlandırıldığını
ve limit aşımlarında (cap / günlük zarar / sektör) pozisyonun açılmadığını
uçtan uca garanti eder. Risk parametreleri değişirse testleri bilinçli
güncelleyin.

Pipeline covered here:
1. ``calculate`` → stop/target + base position size (risk budget + cap)
2. ``apply_portfolio_risk`` → correlation scale / block
3. ``apply_signal_probability`` → daily-loss / liquidity / probability gates
4. ``check_sector_limit`` → sector concentration gate
5. ``daily_loss_limit_reached`` / ``set_daily_realized_pnl`` → risk-off day
"""

from __future__ import annotations

import pandas as pd
import pytest

from bist_bot.config.settings import settings
from bist_bot.risk import RiskLevels, RiskManager


def build_ohlcv_frame(
    *,
    n: int = 40,
    scale: float = 1.0,
    atr: float = 2.0,
    base: float = 100.0,
) -> pd.DataFrame:
    """Deterministic OHLCV+ATR frame used as a mock market snapshot."""
    rows: list[dict[str, float]] = []
    for idx in range(n):
        px = base + idx * scale
        rows.append(
            {
                "open": px,
                "high": px + 2.0,
                "low": px - 2.0,
                "close": px + 1.0,
                "atr": atr,
                "volume": 10_000.0 + idx * 10.0,
            }
        )
    return pd.DataFrame(rows)


def _last_price(df: pd.DataFrame) -> float:
    return float(df["close"].iloc[-1])


def _cap_shares(capital: float, price: float, max_position_cap_pct: float) -> int:
    if price <= 0:
        return 0
    return int(capital * (max_position_cap_pct / 100.0) / price)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------


def test_normal_signal_position_respects_max_position_cap() -> None:
    """Normal STRONG_BUY-like path: size > 0 and never exceeds MAX_POSITION_CAP_PCT."""
    capital = 100_000.0
    cap_pct = 5.0
    manager = RiskManager(capital=capital, max_risk_per_trade_pct=2.0)
    manager.max_position_cap_pct = cap_pct

    df = build_ohlcv_frame()
    price = _last_price(df)
    levels = manager.calculate(df)

    assert levels.position_size > 0
    assert levels.final_stop < price
    assert levels.final_target > price
    assert levels.position_size <= _cap_shares(capital, price, cap_pct)
    notional = levels.position_size * price
    assert notional <= capital * (cap_pct / 100.0) + 1e-6


def test_insufficient_capital_yields_zero_position() -> None:
    """Sermaye yetersiz: price ≫ capital * cap → position_size == 0 (no open)."""
    manager = RiskManager(capital=50.0, max_risk_per_trade_pct=2.0)
    manager.max_position_cap_pct = 5.0

    levels = manager.calculate(build_ohlcv_frame())
    assert levels.position_size == 0
    assert levels.max_loss_tl == 0


def test_high_risk_budget_is_hard_capped_at_max_position_cap_pct() -> None:
    """Maksimum cap: agresif risk bütçesi bile MAX_POSITION_CAP_PCT'yi aşamaz."""
    capital = 1_000_000.0
    cap_pct = 5.0
    # Inflated risk % would otherwise request a huge size; cap must bind.
    manager = RiskManager(capital=capital, max_risk_per_trade_pct=50.0)
    manager.max_position_cap_pct = cap_pct

    df = build_ohlcv_frame()
    price = _last_price(df)
    levels = manager.calculate(df)
    exact_cap = _cap_shares(capital, price, cap_pct)

    assert exact_cap > 0
    assert levels.position_size == exact_cap
    assert levels.position_size * price <= capital * (cap_pct / 100.0) + price


def test_zero_capital_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="capital must be greater than zero"):
        RiskManager(capital=0)


# ---------------------------------------------------------------------------
# Daily loss cap (risk-off)
# ---------------------------------------------------------------------------


def test_daily_loss_limit_reached_when_loss_hits_cap() -> None:
    """Limit aşıldı: realized PnL <= -capital * DAILY_LOSS_CAP_PCT / 100 → risk off."""
    capital = 100_000.0
    manager = RiskManager(capital=capital)
    manager.daily_loss_cap_pct = 3.0

    assert manager.daily_loss_limit_reached() is False

    # Exactly at the cap is already risk-off (<=).
    manager.set_daily_realized_pnl(-(capital * 0.03))
    assert manager.daily_loss_limit_reached() is True

    manager.set_daily_realized_pnl(-(capital * 0.03) - 1.0)
    assert manager.daily_loss_limit_reached() is True


def test_daily_loss_under_cap_allows_trading() -> None:
    """Limit altında: zarar cap'in üstünde (daha az negatif) → pozisyon açılabilir."""
    capital = 100_000.0
    manager = RiskManager(capital=capital)
    manager.daily_loss_cap_pct = 3.0
    manager.min_liquidity_value_tl = 0.0  # bypass liquidity filter for this test
    manager.set_daily_realized_pnl(-1_000.0)  # 1% < 3%

    assert manager.daily_loss_limit_reached() is False

    df = build_ohlcv_frame()
    price = _last_price(df)
    levels = manager.calculate(df)
    assert levels.position_size > 0

    sized = manager.apply_signal_probability(df, price, levels, signal_probability=0.70)
    assert sized.blocked_by_daily_loss is False
    assert sized.position_size > 0


def test_daily_loss_cap_blocks_probability_sizing() -> None:
    """Günlük zarar cap'i aşıldığında apply_signal_probability pozisyonu 0'lar."""
    capital = 100_000.0
    manager = RiskManager(capital=capital, max_risk_per_trade_pct=2.0)
    manager.max_position_cap_pct = 5.0
    manager.daily_loss_cap_pct = 3.0
    manager.min_signal_probability = 0.50
    manager.min_liquidity_value_tl = 0.0

    df = build_ohlcv_frame()
    price = _last_price(df)
    levels = manager.calculate(df)
    assert levels.position_size > 0

    manager.set_daily_realized_pnl(-5_000.0)  # 5% > 3%
    assert manager.daily_loss_limit_reached() is True

    blocked = manager.apply_signal_probability(df, price, levels, signal_probability=0.80)
    assert blocked.position_size == 0
    assert blocked.blocked_by_daily_loss is True
    assert blocked.max_loss_tl == 0.0


def test_disabled_daily_loss_cap_never_trips() -> None:
    """DAILY_LOSS_CAP_PCT <= 0 means the gate is off."""
    manager = RiskManager(capital=100_000.0)
    manager.daily_loss_cap_pct = 0.0
    manager.set_daily_realized_pnl(-50_000.0)
    assert manager.daily_loss_limit_reached() is False


# ---------------------------------------------------------------------------
# Sector concentration limit
# ---------------------------------------------------------------------------


def test_sector_limit_blocks_when_sector_slots_full() -> None:
    """Sektör doldu: limit = MAX_SECTOR_CAP_PCT / MAX_POSITION_CAP_PCT adet.

    With cap 5% and sector cap 10% → only 2 HAVACILIK slots; third is rejected.
    """
    manager = RiskManager(capital=100_000.0)
    manager.max_position_cap_pct = 5.0
    manager.max_sector_cap_pct = 10.0

    # Sanity: known aviation names map to the same sector in settings.
    assert settings.SECTOR_MAP.get("THYAO.IS") == "HAVACILIK"
    assert settings.SECTOR_MAP.get("PGSUS.IS") == "HAVACILIK"
    assert settings.SECTOR_MAP.get("TAVHL.IS") == "HAVACILIK"

    assert manager.check_sector_limit("THYAO.IS") is True
    assert manager.check_sector_limit("PGSUS.IS") is True
    assert manager.check_sector_limit("TAVHL.IS") is False  # sector full

    manager.reset_sectors()
    assert manager.check_sector_limit("TAVHL.IS") is True


def test_unknown_sector_ticker_is_not_blocked() -> None:
    """SECTOR_MAP'te olmayan ticker sektör limitine takılmaz."""
    manager = RiskManager(capital=100_000.0)
    manager.max_position_cap_pct = 5.0
    manager.max_sector_cap_pct = 5.0  # limit = 1 for mapped sectors

    unknown = "ZZZZZ.IS"
    assert settings.SECTOR_MAP.get(unknown) is None
    assert manager.check_sector_limit(unknown) is True
    assert manager.check_sector_limit(unknown) is True


# ---------------------------------------------------------------------------
# Correlation / portfolio risk
# ---------------------------------------------------------------------------


def test_correlation_cluster_blocks_additional_highly_related_name() -> None:
    """Korelasyon kümesi dolunca yeni aday blocked_by_correlation + size 0."""
    manager = RiskManager(capital=10_000.0)
    manager.correlation_max_cluster = 2
    manager.correlation_threshold = 0.70

    manager.register_position("AKBNK.IS", build_ohlcv_frame(scale=1.0))
    manager.register_position("GARAN.IS", build_ohlcv_frame(scale=1.01))
    manager.register_position("YKBNK.IS", build_ohlcv_frame(scale=1.02))

    base = RiskLevels(
        final_stop=95.0,
        final_target=110.0,
        position_size=10,
        volatility_scale=1.0,
        correlation_scale=1.0,
    )
    adjusted = manager.apply_portfolio_risk(
        "ISCTR.IS",
        build_ohlcv_frame(scale=1.03),
        base,
    )

    assert adjusted.blocked_by_correlation is True
    assert adjusted.position_size == 0
    assert adjusted.correlation_scale == 0.0


def test_end_to_end_risk_pipeline_happy_path() -> None:
    """Full chain: calculate → portfolio risk → probability sizing still opens size."""
    capital = 100_000.0
    manager = RiskManager(capital=capital, max_risk_per_trade_pct=2.0)
    manager.max_position_cap_pct = 5.0
    manager.daily_loss_cap_pct = 3.0
    manager.min_signal_probability = 0.50
    manager.min_liquidity_value_tl = 0.0
    manager.set_daily_realized_pnl(0.0)

    df = build_ohlcv_frame()
    price = _last_price(df)

    levels = manager.calculate(df)
    assert levels.position_size > 0

    levels = manager.apply_portfolio_risk("THYAO.IS", df, levels)
    assert levels.blocked_by_correlation is False
    assert levels.position_size > 0

    levels = manager.apply_signal_probability(df, price, levels, signal_probability=0.65)
    assert levels.blocked_by_daily_loss is False
    assert levels.blocked_by_probability is False
    assert levels.position_size > 0
    assert levels.position_size <= _cap_shares(capital, price, manager.max_position_cap_pct)
    assert manager.check_sector_limit("THYAO.IS") is True
