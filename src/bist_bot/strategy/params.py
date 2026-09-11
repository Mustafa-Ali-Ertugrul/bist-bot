"""Centralized strategy threshold and scoring defaults.

Override önceliği (mevcut de-facto davranış, testlerle sabitlenmiştir):

1. ``StrategyParams`` dataclass default'u (kanonik kod-içi değer)
2. ``config.settings`` env değeri (construction anında ``default_factory`` ile okunur)
3. Profil explicit değeri (``conservative()`` / ``champion_wr()`` içinde verilen
   alanlar env'i ezer — örn. ``conservative().adx_threshold`` her zaman 20.0'dır)
4. Çağrı-bazlı açık override (``StrategyParams(adx_threshold=35)`` veya
   fonksiyonlara verilen ``params`` nesnesi)

Env'i profile üstün kılmak (2<->3 sırasını değiştirmek) davranış değişikliğidir;
ayrı karar gerektirir, bu refaktörde yapılmamıştır.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from bist_bot.config.settings import settings


@dataclass
class StrategyParams:
    """Strateji motoru için dışarıdan yapılandırılabilir parametreler."""

    # Eşik değerlerinin tek kaynağı `config.settings` içindeki ayarlardır.
    strong_buy_threshold: float = field(
        default_factory=lambda: float(settings.STRONG_BUY_THRESHOLD)
    )
    buy_threshold: float = 20.0
    # Upper bound of the actionable buy band. Scores above this are
    # overextended (backtest: 40+ scores drag WR down) and never actionable,
    # regardless of label. Default 100.0 = effectively no cap.
    max_actionable_score: float = 100.0
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
    chase_block_enabled: bool = False
    chase_blocked_score_cap: float = 20.0
    chase_strong_trend_cap: float = 30.0
    # Chase "aşırı uzama" tespit eşikleri (profil bağımsız; yalnızca
    # overextended kararını belirler, cap büyüklükleri yukarıda kalır).
    chase_cci_threshold: float = 150.0
    chase_resist_pct: float = 1.0
    chase_strong_trend_adx: float = 30.0
    mtf_confluence_block_enabled: bool = True
    # P1-B deneyi (Deney C): aşırı satım bileşenleri için trend onayı.
    # Açıkken BB BELOW_LOWER ve CCI < -100 puanları, close > SMA20 veya
    # plus_di > minus_di (yönlü yükseliş teyidi) koşullarından hiçbiri
    # sağlanmıyorsa ``oversold_unconfirmed_score_multiplier`` ile çarpılır.
    # ADX tek başına yetmez (yönsüz güç ölçüsü). Ölçüm: 0.5 çarpanı hiçbir
    # skoru eşik altına düşürmedi (etkisiz) → 0.0 varyantı da test edilir.
    # Varsayılanlar kapalı/0.5 → mevcut davranış değişmez.
    oversold_requires_trend_confirm: bool = False
    oversold_unconfirmed_score_multiplier: float = 0.5
    # Deney F (P0/P1 kanıtı): long adaylar için fiyat-hacim boğa teyidi şartı.
    # Açıkken skoru buy_threshold'u geçen long aday
    # ``price_volume_direction != BULLISH_CONFIRMATION`` ise reddedilir.
    # Kanıt: 508 sinyalde pv_bull=0 alt kümesi (n=153) mean -%1.51, up %39;
    # pv_bull=1 (n=355) mean +%1.03, up %56. Varsayılan kapalı → davranış değişmez.
    pv_confirmation_required: bool = False
    counter_trend_multiplier: float = 0.3
    agreement_gate_enabled: bool = False
    agreement_gate_threshold: float = 0.5
    agreement_low_cap: float = 30.0
    score_sma_death_cross: float = 12.0

    # ------------------------------------------------------------------
    # Research profile — normalized component scoring (additive, opt-in)
    # ------------------------------------------------------------------
    normalized_component_scoring: bool = False
    component_weight_momentum: float = 0.15
    component_weight_trend: float = 0.60
    component_weight_volume: float = 0.15
    component_weight_structure: float = 0.10

    # RSI Parametreleri (Aşama 1: oversold/overbought settings'e bağlı —
    # daha önce kod-içi 30/70 ile env RSI_OVERSOLD/RSI_OVERBOUGHT çift
    # tanımlıydı. Diğer bantlar kod-içi default olarak kalır.)
    rsi_oversold_extreme: float = 25.0
    rsi_oversold: float = field(default_factory=lambda: float(settings.RSI_OVERSOLD))
    rsi_neutral_low: float = 40.0
    rsi_neutral_high: float = 60.0
    rsi_overbought: float = field(default_factory=lambda: float(settings.RSI_OVERBOUGHT))
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

    # ------------------------------------------------------------------
    # Aşama 1: scoring bölge eşikleri (env'den, default'lar kodda doğrulandı)
    # ------------------------------------------------------------------
    stoch_oversold: float = field(default_factory=lambda: float(settings.STOCH_OVERSOLD))
    stoch_overbought: float = field(default_factory=lambda: float(settings.STOCH_OVERBOUGHT))
    stoch_trend_mid: float = field(default_factory=lambda: float(settings.STOCH_TREND_MID))
    cci_min: float = field(default_factory=lambda: float(settings.CCI_MIN))
    cci_max: float = field(default_factory=lambda: float(settings.CCI_MAX))
    bb_pct_low: float = field(default_factory=lambda: float(settings.BB_PCT_LOW))
    bb_pct_high: float = field(default_factory=lambda: float(settings.BB_PCT_HIGH))
    adx_strong_edge: float = field(default_factory=lambda: float(settings.ADX_STRONG_EDGE))
    sr_distance_pct: float = field(default_factory=lambda: float(settings.SR_DISTANCE_PCT))

    # Bileşen cap'leri (scoring clamp'leri + normalize araştırma modu paydası).
    momentum_score_cap: float = field(default_factory=lambda: float(settings.MOMENTUM_SCORE_CAP))
    trend_score_cap: float = field(default_factory=lambda: float(settings.TREND_SCORE_CAP))
    volume_score_cap: float = field(default_factory=lambda: float(settings.VOLUME_SCORE_CAP))
    structure_score_cap: float = field(default_factory=lambda: float(settings.STRUCTURE_SCORE_CAP))

    # Rejim sabitleri (detect_regime + vektörel ikizi aynı helper'dan okur).
    regime_lookback: int = field(default_factory=lambda: int(settings.REGIME_LOOKBACK))
    regime_min_bars: int = field(default_factory=lambda: int(settings.REGIME_MIN_BARS))
    regime_trend_adx: float = field(default_factory=lambda: float(settings.REGIME_TREND_ADX))
    regime_weak_adx: float = field(default_factory=lambda: float(settings.REGIME_WEAK_ADX))
    regime_di_ratio: float = field(default_factory=lambda: float(settings.REGIME_DI_RATIO))
    regime_momentum_pct: float = field(default_factory=lambda: float(settings.REGIME_MOMENTUM_PCT))

    # Agreement bantları (engine_filters classify + agree oranı).
    agreement_full: float = field(default_factory=lambda: float(settings.AGREEMENT_FULL))
    agreement_min: float = field(default_factory=lambda: float(settings.AGREEMENT_MIN))
    agreement_divisor: float = field(default_factory=lambda: float(settings.AGREEMENT_DIVISOR))

    # Korelasyon pairwise fallback minimum örtüşen bar (risk/correlation).
    corr_fallback_min_bars: int = field(
        default_factory=lambda: int(settings.CORR_FALLBACK_MIN_BARS)
    )

    # ------------------------------------------------------------------
    # Trade-actionability contract (single source for all downstream layers)
    # ------------------------------------------------------------------
    def buy_actionable_score(self, score: float) -> bool:
        """Return True when `score` sits inside the actionable buy band."""
        return self.buy_threshold <= score <= self.max_actionable_score

    def sell_actionable_score(self, score: float) -> bool:
        """Return True when `score` crosses the sell-side trade threshold."""
        return score <= self.sell_threshold

    def validate(self) -> list[str]:
        """Return logical inconsistencies in this instance (empty = valid).

        Aşama 1: preflight (``settings.collect_preflight_errors``) ile aynı
        kuralları paylaşır — bkz. modül fonksiyonu ``validate_strategy_params``.
        NaN/sonsuz float'lar reddedilir.
        """
        return validate_strategy_params(self)

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
    def research_v1(cls) -> StrategyParams:
        """Research profile — inherits conservative semantics, enables normalized scoring.

        All conservative thresholds (buy 25 / sell -25, conservative RSI/stochastic,
        counter-trend 0, OBV cap, etc.) are preserved verbatim. The only behavioral
        addition is ``normalized_component_scoring=True`` which switches the
        component-combination math to a weighted, normalized form (see
        ``scoring.combine_component_scores``).
        """
        params = cls.conservative()
        params.normalized_component_scoring = True
        return params

    @classmethod
    def champion_wr(cls) -> StrategyParams:
        """Champion WR profile (challenge 2026-08-29: 76.4% backtest WR).

        Replicates the winning configuration live: score band 28-33
        (40+ overextended scores excluded), pv-confirmation gate on,
        RR/floor handled via FALLBACK_TARGET_RR env. Sell side unchanged.
        """
        params = cls.conservative()
        params.buy_threshold = 28.0
        params.sell_threshold = -28.0
        params.max_actionable_score = 33.0
        params.pv_confirmation_required = True
        return params

    @classmethod
    def from_settings(cls) -> StrategyParams:
        """Return the right profile instance based on STRATEGY_PROFILE."""
        profile = getattr(settings, "STRATEGY_PROFILE", "conservative")
        if profile == "conservative":
            return cls.conservative()
        if profile == "research_v1":
            return cls.research_v1()
        if profile == "champion":
            return cls.champion_wr()
        return cls()


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def validate_strategy_params(params: Any) -> list[str]:
    """Shared Aşama 1 rule set for StrategyParams instances.

    Hem ``StrategyParams.validate()`` hem de settings preflight bu fonksiyonu
    kullanır; kurallar tek kaynaktan gelir. ``params`` duck-typed okunur
    (getattr + default), böylece kısmi stub nesneler de doğrulanabilir.
    """
    errors: list[str] = []

    def _num(name: str, default: float) -> float | None:
        try:
            value = float(getattr(params, name, default))
        except (TypeError, ValueError):
            errors.append(f"{name} sayısal olmalı")
            return None
        if not _is_finite_number(value):
            errors.append(f"{name} sonlu sayı olmalı")
            return None
        return value

    def _int(name: str, default: int) -> int | None:
        try:
            value = int(getattr(params, name, default))
        except (TypeError, ValueError):
            errors.append(f"{name} tam sayı olmalı")
            return None
        return value

    stoch_lo = _num("stoch_oversold", 20.0)
    stoch_hi = _num("stoch_overbought", 80.0)
    stoch_mid = _num("stoch_trend_mid", 50.0)
    if stoch_lo is not None and not (0 <= stoch_lo <= 100):
        errors.append("stoch_oversold 0-100 aralığında olmalı")
    if stoch_hi is not None and not (0 <= stoch_hi <= 100):
        errors.append("stoch_overbought 0-100 aralığında olmalı")
    if stoch_lo is not None and stoch_hi is not None and not (stoch_lo < stoch_hi):
        errors.append("stoch_oversold < stoch_overbought olmalı")
    if stoch_mid is not None and not (0 <= stoch_mid <= 100):
        errors.append("stoch_trend_mid 0-100 aralığında olmalı")
    if (
        stoch_lo is not None
        and stoch_mid is not None
        and stoch_hi is not None
        and not (stoch_lo <= stoch_mid <= stoch_hi)
    ):
        errors.append("stoch_trend_mid, stoch bandı içinde olmalı")

    cci_min = _num("cci_min", -50.0)
    cci_max = _num("cci_max", 50.0)
    if cci_min is not None and cci_max is not None and not (cci_min < cci_max):
        errors.append("cci_min < cci_max olmalı")

    bb_lo = _num("bb_pct_low", 0.2)
    bb_hi = _num("bb_pct_high", 0.8)
    if bb_lo is not None and not (0 <= bb_lo <= 1):
        errors.append("bb_pct_low 0-1 aralığında olmalı")
    if bb_hi is not None and not (0 <= bb_hi <= 1):
        errors.append("bb_pct_high 0-1 aralığında olmalı")
    if bb_lo is not None and bb_hi is not None and not (bb_lo < bb_hi):
        errors.append("bb_pct_low < bb_pct_high olmalı")

    adx_edge = _num("adx_strong_edge", 25.0)
    if adx_edge is not None and adx_edge < 0:
        errors.append("adx_strong_edge negatif olamaz")
    sr_pct = _num("sr_distance_pct", 2.0)
    if sr_pct is not None and sr_pct < 0:
        errors.append("sr_distance_pct negatif olamaz")

    for cap_name in (
        "momentum_score_cap",
        "trend_score_cap",
        "volume_score_cap",
        "structure_score_cap",
    ):
        cap = _num(cap_name, 1.0)
        if cap is not None and cap < 0:
            errors.append(f"{cap_name} negatif olamaz")

    agr_full = _num("agreement_full", 0.75)
    agr_min = _num("agreement_min", 0.5)
    agr_div = _num("agreement_divisor", 4.0)
    if agr_full is not None and not (0 <= agr_full <= 1):
        errors.append("agreement_full 0-1 aralığında olmalı")
    if agr_min is not None and not (0 <= agr_min <= 1):
        errors.append("agreement_min 0-1 aralığında olmalı")
    if agr_min is not None and agr_full is not None and not (agr_min <= agr_full):
        errors.append("agreement_min <= agreement_full olmalı")
    if agr_div is not None and agr_div <= 0:
        errors.append("agreement_divisor pozitif olmalı")

    for int_name in ("regime_lookback", "regime_min_bars"):
        int_value = _int(int_name, 1)
        if int_value is not None and int_value < 1:
            errors.append(f"{int_name} >= 1 olmalı")
    trend_adx = _num("regime_trend_adx", 20.0)
    weak_adx = _num("regime_weak_adx", 15.0)
    if trend_adx is not None and trend_adx < 0:
        errors.append("regime_trend_adx negatif olamaz")
    if weak_adx is not None and weak_adx < 0:
        errors.append("regime_weak_adx negatif olamaz")
    if trend_adx is not None and weak_adx is not None and not (trend_adx >= weak_adx):
        errors.append("regime_trend_adx >= regime_weak_adx olmalı")
    di_ratio = _num("regime_di_ratio", 1.25)
    if di_ratio is not None and di_ratio <= 0:
        errors.append("regime_di_ratio pozitif olmalı")
    mom_pct = _num("regime_momentum_pct", 3.0)
    if mom_pct is not None and mom_pct < 0:
        errors.append("regime_momentum_pct negatif olamaz")

    min_bars = _int("corr_fallback_min_bars", 10)
    if min_bars is not None and min_bars < 2:
        errors.append("corr_fallback_min_bars >= 2 olmalı")

    return errors
