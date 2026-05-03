"""Centralized strategy threshold and scoring defaults."""

from dataclasses import dataclass, field

from bist_bot.config.settings import settings


@dataclass
class StrategyParams:
    """Strateji motoru için dışarıdan yapılandırılabilir parametreler."""

    # Eşik değerlerinin tek kaynağı `config.settings` içindeki ayarlardır.
    strong_buy_threshold: float = field(
        default_factory=lambda: float(settings.STRONG_BUY_THRESHOLD)
    )
    buy_threshold: float = field(default_factory=lambda: float(settings.BUY_THRESHOLD))
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
