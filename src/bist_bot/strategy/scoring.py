"""Scoring components used by the strategy engine."""

from __future__ import annotations

import pandas as pd

from bist_bot.config.settings import settings


def score_momentum(params, last, prev) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    rsi = last.get("rsi")
    if pd.notna(rsi):
        if rsi < params.rsi_oversold_extreme:
            score += params.score_rsi_extreme
            reasons.append(f"RSI çok düşük ({rsi:.1f}) → Aşırı satım")
        elif rsi < params.rsi_oversold:
            score += params.score_rsi_normal
            reasons.append(f"RSI düşük ({rsi:.1f}) → Satım bölgesi")
        elif rsi < params.rsi_neutral_low:
            score += params.score_rsi_weak_low
            reasons.append(f"RSI düşük-nötr ({rsi:.1f})")
        elif rsi > params.rsi_overbought_extreme:
            score -= params.score_rsi_extreme
            reasons.append(f"RSI çok yüksek ({rsi:.1f}) → Aşırı alım")
        elif rsi > params.rsi_overbought:
            score -= params.score_rsi_normal
            reasons.append(f"RSI yüksek ({rsi:.1f}) → Alım bölgesi")
        elif rsi > params.rsi_neutral_high:
            score -= params.score_rsi_weak_high
            reasons.append(f"RSI yüksek-nötr ({rsi:.1f})")
        else:
            reasons.append(f"RSI nötr ({rsi:.1f})")

    stoch_k = last.get("stoch_k")
    stoch_d = last.get("stoch_d")
    if pd.notna(stoch_k) and pd.notna(stoch_d):
        stoch_cross = last.get("stoch_cross", "NONE")
        if stoch_cross == "BULLISH":
            score += params.score_stoch_cross
            reasons.append(
                f"Stochastic Bullish Cross (K:{stoch_k:.0f}, D:{stoch_d:.0f})"
            )
        elif stoch_cross == "BEARISH":
            score -= params.score_stoch_cross
            reasons.append(
                f"Stochastic Bearish Cross (K:{stoch_k:.0f}, D:{stoch_d:.0f})"
            )

        if stoch_k < 20 and stoch_d < 20:
            score += params.score_stoch_extreme
            reasons.append(f"Stochastic aşırı satım bölgesi (K:{stoch_k:.0f})")
        elif stoch_k > 80 and stoch_d > 80:
            score -= params.score_stoch_extreme
            reasons.append(f"Stochastic aşırı alım bölgesi (K:{stoch_k:.0f})")

        if stoch_k > stoch_d and stoch_k < 50:
            score += params.score_stoch_trend
            reasons.append("Stochastic yükseliş eğilimi")
        elif stoch_k < stoch_d and stoch_k > 50:
            score -= params.score_stoch_trend
            reasons.append("Stochastic düşüş eğilimi")

    cci = last.get("cci")
    if pd.notna(cci):
        if cci < -100:
            score += params.score_cci_extreme
            reasons.append(f"CCI aşırı satım ({cci:.0f})")
        elif cci < -50:
            score += params.score_cci_normal
            reasons.append(f"CCI düşük ({cci:.0f})")
        elif cci > 100:
            score -= params.score_cci_extreme
            reasons.append(f"CCI aşırı alım ({cci:.0f})")
        elif cci > 50:
            score -= params.score_cci_normal
            reasons.append(f"CCI yüksek ({cci:.0f})")

    return score, reasons


def score_trend(params, last, prev) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    adx = last.get("adx")
    ema_long = last.get(f"ema_{settings.EMA_LONG}")
    if pd.notna(ema_long):
        price = last["close"]
        above_ema = price > ema_long
        last_above_ema = prev["close"] > prev.get(f"ema_{settings.EMA_LONG}", ema_long)
        if above_ema and not last_above_ema:
            reasons.append(f"Fiyat EMA{settings.EMA_LONG}'i kesti (yukarı)")
        elif above_ema:
            if pd.notna(adx) and adx >= getattr(settings, "ADX_THRESHOLD", 20):
                score += params.score_ema_cross
                reasons.append(f"yükseliş trendi (EMA{settings.EMA_LONG} üzerinde)")
        elif not above_ema and last_above_ema:
            reasons.append(f"Fiyat EMA{settings.EMA_LONG}'i kesti (aşağı)")

    sma_cross = last.get("sma_cross", "NONE")
    if sma_cross == "GOLDEN_CROSS":
        score += params.score_sma_golden_cross
        reasons.append("SMA Golden Cross ✨ → Yükseliş sinyali")
    elif sma_cross == "DEATH_CROSS":
        score -= params.score_sma_golden_cross
        reasons.append("SMA Death Cross 💀 → Düşüş sinyali")
    else:
        sma_fast = last.get(f"sma_{settings.SMA_FAST}")
        sma_slow = last.get(f"sma_{settings.SMA_SLOW}")
        if pd.notna(sma_fast) and pd.notna(sma_slow):
            if sma_fast > sma_slow:
                score += params.score_sma_trend
                reasons.append("SMA trend yukarı")
            else:
                score -= params.score_sma_trend
                reasons.append("SMA trend aşağı")

    ema_cross = last.get("ema_cross", "NONE")
    if ema_cross == "BULLISH":
        score += params.score_ema_cross
        reasons.append("EMA Bullish Cross ⚡ → Hızlı yükseliş")
    elif ema_cross == "BEARISH":
        score -= params.score_ema_cross
        reasons.append("EMA Bearish Cross ⚡ → Hızlı düşüş")

    macd_cross = last.get("macd_cross", "NONE")
    macd_hist = last.get("macd_histogram")
    macd_hist_inc = last.get("macd_hist_increasing", False)

    if macd_cross == "BULLISH":
        score += params.score_macd_cross
        reasons.append("MACD Bullish Crossover 📈")
    elif macd_cross == "BEARISH":
        score -= params.score_macd_cross
        reasons.append("MACD Bearish Crossover 📉")

    if pd.notna(macd_hist):
        if macd_hist > 0 and macd_hist_inc:
            score += params.score_macd_hist_strong
            reasons.append(f"MACD Histogram güçleniyor ({macd_hist:.2f})")
        elif macd_hist > 0:
            score += params.score_macd_hist_weak
            reasons.append(f"MACD Histogram pozitif ({macd_hist:.2f})")
        elif macd_hist < 0 and not macd_hist_inc:
            score -= params.score_macd_hist_strong
            reasons.append(f"MACD Histogram zayıflıyor ({macd_hist:.2f})")
        else:
            score -= params.score_macd_hist_weak
            reasons.append(f"MACD Histogram negatif ({macd_hist:.2f})")

    plus_di = last.get("plus_di")
    minus_di = last.get("minus_di")
    if pd.notna(adx) and pd.notna(plus_di) and pd.notna(minus_di):
        if adx > 25:
            if plus_di > minus_di:
                score += params.score_adx_strong
                reasons.append(
                    f"Güçlü yükseliş trendi (ADX:{adx:.0f}, +DI>{minus_di:.0f})"
                )
            else:
                score -= params.score_adx_strong
                reasons.append(f"Güçlü düşüş trendi (ADX:{adx:.0f}, -DI>{plus_di:.0f})")
        else:
            if plus_di > minus_di:
                score += params.score_adx_weak
                reasons.append(f"Zayıf yükseliş trendi (ADX:{adx:.0f})")
            else:
                score -= params.score_adx_weak
                reasons.append(f"Zayıf düşüş trendi (ADX:{adx:.0f})")

    di_cross = last.get("di_cross", "NONE")
    if di_cross == "BULLISH":
        score += params.score_di_cross
        reasons.append("+DI/-DI Bullish Cross")
    elif di_cross == "BEARISH":
        score -= params.score_di_cross
        reasons.append("+DI/-DI Bearish Cross")

    return score, reasons


def score_volume(params, last) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    volume_sma_20 = last.get("volume_sma_20")
    volume = last.get("volume")
    if pd.notna(volume_sma_20) and pd.notna(volume):
        vol_ratio = volume / volume_sma_20
        min_vol_ratio = getattr(settings, "VOLUME_CONFIRM_MULTIPLIER", 1.5)
        if vol_ratio >= min_vol_ratio:
            score += params.score_volume_confirm
            reasons.append(f"Hacim onayı ({vol_ratio:.1f}x ort)")

    vol_spike = last.get("volume_spike", False)
    vol_ratio = last.get("volume_ratio", 1.0)
    pv_confirm = last.get("price_volume_confirm", False)
    vol_trend = last.get("volume_trend", "FLAT")

    if vol_spike:
        price_change = last["close"] - last.get(
            "_prev_close_for_scoring", last["close"]
        )
        if price_change > 0:
            score += params.score_volume_spike
            reasons.append(f"Hacim patlaması + yükseliş ({vol_ratio:.1f}x)")
        else:
            score -= params.score_volume_spike
            reasons.append(f"Hacim patlaması + düşüş ({vol_ratio:.1f}x)")

    if pv_confirm:
        score += params.score_price_volume_confirm
        reasons.append("Fiyat-Hacim uyumu ✓")

    if vol_trend == "INCREASING":
        score += params.score_volume_trend
        reasons.append("Hacim artıyor 📊")
    elif vol_trend == "DECREASING":
        score -= params.score_volume_trend
        reasons.append("Hacim azalıyor 📊")

    obv_trend = last.get("obv_trend", "FLAT")
    if obv_trend == "UP":
        score += params.score_obv_trend
        reasons.append("OBV yükseliş trendi → Akış var")
    elif obv_trend == "DOWN":
        score -= params.score_obv_trend
        reasons.append("OBV düşüş trendi → Çıkış var")

    return score, reasons


def score_structure(params, last) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    bb_pos = last.get("bb_position", "MIDDLE")
    bb_pct = last.get("bb_percent")
    bb_squeeze = last.get("bb_squeeze", False)

    if bb_pos == "BELOW_LOWER":
        score += params.score_bollinger_extreme
        reasons.append("Fiyat Bollinger alt bandının altında → Alım fırsatı")
    elif bb_pos == "ABOVE_UPPER":
        score -= params.score_bollinger_extreme
        reasons.append("Fiyat Bollinger üst bandının üstünde → Aşırı uzamış")
    elif pd.notna(bb_pct):
        if bb_pct < 0.2:
            score += params.score_bollinger_percent
            reasons.append(f"Bollinger %B düşük ({bb_pct:.2f})")
        elif bb_pct > 0.8:
            score -= params.score_bollinger_percent
            reasons.append(f"Bollinger %B yüksek ({bb_pct:.2f})")

    if bb_squeeze:
        reasons.append("Bollinger Squeeze → Patlama bekleniyor ⚠️")

    dist_support = last.get("dist_to_support_pct", 50)
    dist_resist = last.get("dist_to_resistance_pct", 50)

    if pd.notna(dist_support) and dist_support < 2:
        score += params.score_sr_distance
        reasons.append(f"Fiyat desteğe yakın (%{dist_support:.1f})")
    elif pd.notna(dist_resist) and dist_resist < 2:
        score -= params.score_sr_distance
        reasons.append(f"Fiyat dirence yakın (%{dist_resist:.1f})")

    rsi_div = last.get("rsi_divergence", "NONE")
    if rsi_div == "BULLISH":
        score += params.score_rsi_divergence
        reasons.append("🔥 RSI Bullish Divergence → Güçlü dönüş sinyali")
    elif rsi_div == "BEARISH":
        score -= params.score_rsi_divergence
        reasons.append("🔥 RSI Bearish Divergence → Güçlü dönüş sinyali")

    macd_div = last.get("macd_divergence", "NONE")
    if macd_div == "BULLISH":
        score += params.score_macd_divergence
        reasons.append("🔥 MACD Bullish Divergence → Güçlü dönüş sinyali")
    elif macd_div == "BEARISH":
        score -= params.score_macd_divergence
        reasons.append("🔥 MACD Bearish Divergence → Güçlü dönüş sinyali")

    return score, reasons
