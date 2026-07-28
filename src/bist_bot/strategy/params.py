"""Centralized strategy threshold and scoring defaults."""

from __future__ import annotations

from dataclasses import dataclass, field

from bist_bot.config.settings import settings


@dataclass
class StrategyParams:
    """Strateji motoru için dışarıdan yapılandırılabilir parametreler."""

    # Eşik değerlerinin tek kaynağı `config.settings` içindeki ayarlardır.
    strong_buy_threshold: float = field(
        default_factory=lambda: float(settings.STRONG_BUY_THRESHOLD)
    )
    buy_threshold: float = 20.0
    weak_buy_threshold: float = field(default_factory=lambda: float(settings.WEAK_BUY_THRESHOLD))
    weak_sell_threshold: float = field(default_factory=lambda: float(settings.WEAK_SELL_THRESHOLD))
    sell_threshold: float = field(default_factory=lambda: float(settings.SELL_THRESHOLD))
    strong_sell_threshold: float = field(
        default_factory=lambda: float(settings.STRONG_SELL_THRESHOLD)
    )
    sideways_extra_threshold: float = field(
        default_factory=lambda: float(settings.SIDEWAYS_EXTRA_THRESHOLD)
    )
    momentum_confirmation_threshold: float = field(
        default_factory=lambda: float(settings.MOMENTUM_CONFIRMATION_THRESHOLD)
    )
    min_trigger_candles: int = 30
    adx_threshold: float = field(default_factory=lambda: float(settings.ADX_THRESHOLD))
    adx_low_trend_penalty: float = 5.0
    sideways_score_multiplier: float = 0.6
    slope_lookback: int = 40
    obv_divergence_block_enabled: bool = False
    obv_divergence_cap: float = 25.0
    chase_block_enabled: bool = True
    chase_blocked_score_cap: float = 20.0
    chase_strong_trend_cap: float = 30.0
    mtf_confluence_block_enabled: bool = True
    counter_trend_multiplier: float = 0.3
    agreement_gate_enabled: bool = False
    agreement_gate_threshold: float = 0.5
    agreement_low_cap: float = 30.0
    score_sma_death_cross: float = 12.0

    # RSI Parametreleri
    rsi_oversold_extreme: float = 25.0
    rsi_oversold: float = 30.0
    rsi_neutral_low: float = 40.0
    rsi_neutral_high: float = 60.0
    rsi_overbought: float = 70.0
    rsi_overbought_extreme: float = 80.0

    # Momentum Skorları
    score_rsi_extreme: float = 18.0
    score_rsi_normal: float = 14.0
    score_rsi_weak_low: float = 7.0
    score_rsi_weak_high: float = 4.0
    score_stoch_cross: float = 8.0
    score_stoch_extreme: float = 6.0
    score_stoch_trend: float = 3.0
    score_cci_extreme: float = 8.0
    score_cci_normal: float = 4.0

    # Trend Skorları
    score_sma_golden_cross: float = 12.0
    score_sma_trend: float = 3.0
    score_ema_cross: float = 10.0
    score_ema_initial_cross: float = 10.0
    score_macd_hist_strong: float = 5.0
    score_macd_hist_weak: float = 3.0
    score_macd_cross: float = 12.0
    score_di_cross: float = 6.0
    score_adx_strong: float = 8.0
    score_adx_weak: float = 3.0

    # Volume / Structure Skorları
    score_volume_confirm: float = 8.0
    score_volume_spike: float = 8.0
    score_price_volume_confirm: float = 2.0
    score_volume_trend: float = 2.0
    score_obv_trend: float = 4.0
    score_bollinger_extreme: float = 10.0
    score_bollinger_percent: float = 5.0
    score_sr_distance: float = 6.0
    score_rsi_divergence: float = 15.0
    score_macd_divergence: float = 12.0

    @classmethod
    def conservative(cls) -> StrategyParams:
        return cls(
            buy_threshold=25.0,
            sell_threshold=-25.0,
            sideways_score_multiplier=0.4,
            adx_threshold=20.0,
            score_rsi_extreme=12.6,
            score_rsi_normal=9.8,
            score_rsi_weak_low=4.9,
            score_rsi_weak_high=2.8,
            score_stoch_cross=5.6,
            score_stoch_extreme=4.2,
            score_stoch_trend=2.1,
            chase_blocked_score_cap=10.0,
            chase_strong_trend_cap=20.0,
            counter_trend_multiplier=0.0,
            agreement_low_cap=15.0,
            slope_lookback=40,
            mtf_confluence_block_enabled=True,
            obv_divergence_block_enabled=True,
            obv_divergence_cap=15.0,
        )

    @classmethod
    def from_settings(cls) -> StrategyParams:
        """Return the right profile instance based on STRATEGY_PROFILE."""
        profile = getattr(settings, "STRATEGY_PROFILE", "conservative")
        if profile == "conservative":
            return cls.conservative()
        return cls()
