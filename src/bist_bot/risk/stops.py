"""Stop and target calculation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_bot.risk.models import RiskLevels


def calc_atr_levels(
    df: pd.DataFrame,
    price: float,
    levels: RiskLevels,
    atr_stop_mult: float,
    atr_target_mult: float,
) -> RiskLevels:
    atr = df.get("atr")
    if atr is not None and pd.notna(atr.iloc[-1]):
        atr_val = float(atr.iloc[-1])
        levels.stop_atr = round(price - (atr_stop_mult * atr_val), 2)
        levels.target_atr = round(price + (atr_target_mult * atr_val), 2)
    return levels


def calc_support_resistance(
    df: pd.DataFrame, price: float, levels: RiskLevels
) -> RiskLevels:
    supports: list[float] = []
    resistances: list[float] = []
    for window in [10, 20, 50]:
        if len(df) >= window:
            supports.append(float(df["low"].tail(window).min()))
            resistances.append(float(df["high"].tail(window).max()))

    valid_supports = [support for support in supports if support < price]
    if valid_supports:
        levels.stop_support = round(max(valid_supports) * 0.995, 2)

    valid_resistances = [resistance for resistance in resistances if resistance > price]
    if valid_resistances:
        levels.target_resistance = round(min(valid_resistances), 2)
    elif resistances:
        levels.target_resistance = round(max(max(resistances) * 1.005, price * 1.02), 2)
    return levels


def calc_fibonacci(df: pd.DataFrame, price: float, levels: RiskLevels) -> RiskLevels:
    lookback = min(60, len(df))
    recent = df.tail(lookback)
    swing_high = float(recent["high"].max())
    swing_low = float(recent["low"].min())
    diff = swing_high - swing_low
    if diff <= 0:
        return levels
    if (diff / price) < 0.05:
        levels.target_fibonacci = round(price, 2)
        return levels

    fib_levels = {
        "fib_236": swing_high - (diff * 0.236),
        "fib_382": swing_high - (diff * 0.382),
        "fib_500": swing_high - (diff * 0.500),
        "fib_618": swing_high - (diff * 0.618),
        "fib_786": swing_high - (diff * 0.786),
    }

    below_fibs = {key: value for key, value in fib_levels.items() if value < price}
    if below_fibs:
        levels.stop_fibonacci = round(max(below_fibs.values()) * 0.995, 2)

    above_fibs = {key: value for key, value in fib_levels.items() if value > price}
    if above_fibs:
        levels.target_fibonacci = round(min(above_fibs.values()), 2)
    else:
        levels.target_fibonacci = round(swing_high, 2)
    return levels


def calc_fixed_percent(
    price: float, levels: RiskLevels, fixed_stop_pct: float, fixed_target_pct: float
) -> RiskLevels:
    levels.stop_percent = round(price * (1 - fixed_stop_pct / 100), 2)
    levels.target_percent = round(price * (1 + fixed_target_pct / 100), 2)
    return levels


def calc_swing_levels(df: pd.DataFrame, price: float, levels: RiskLevels) -> RiskLevels:
    lookback = min(60, len(df))
    if lookback < 5:
        return levels

    recent = df.tail(lookback).iloc[:-2].copy()
    swing_low_mask = (
        (recent["low"] < recent["low"].shift(1))
        & (recent["low"] < recent["low"].shift(2))
        & (recent["low"] < recent["low"].shift(-1))
        & (recent["low"] < recent["low"].shift(-2))
    )
    swing_high_mask = (
        (recent["high"] > recent["high"].shift(1))
        & (recent["high"] > recent["high"].shift(2))
        & (recent["high"] > recent["high"].shift(-1))
        & (recent["high"] > recent["high"].shift(-2))
    )

    swing_lows = recent.loc[swing_low_mask, "low"].dropna().astype(float).tolist()
    swing_highs = recent.loc[swing_high_mask, "high"].dropna().astype(float).tolist()

    valid_lows = [swing_low for swing_low in swing_lows if swing_low < price]
    if valid_lows:
        levels.stop_swing = round(max(valid_lows) * 0.995, 2)

    valid_highs = [swing_high for swing_high in swing_highs if swing_high > price]
    if valid_highs:
        levels.target_swing = round(min(valid_highs), 2)
    return levels


def determine_final_levels(price: float, levels: RiskLevels) -> RiskLevels:
    all_stops = {
        "ATR": levels.stop_atr,
        "Destek": levels.stop_support,
        "Fibonacci": levels.stop_fibonacci,
        "Yüzdelik": levels.stop_percent,
        "Swing": levels.stop_swing,
    }
    valid_stops = {
        key: value for key, value in all_stops.items() if value > 0 and value < price
    }
    reasonable_stops = {
        key: value
        for key, value in valid_stops.items()
        if (price - value) / price > 0.01
    }
    reasonable_stops = {
        key: value
        for key, value in reasonable_stops.items()
        if (price - value) / price < 0.10
    }

    if reasonable_stops:
        best_stop_method = max(reasonable_stops, key=reasonable_stops.get)
        levels.final_stop = reasonable_stops[best_stop_method]
        stop_method = best_stop_method
    elif valid_stops:
        best_stop_method = max(valid_stops, key=valid_stops.get)
        levels.final_stop = valid_stops[best_stop_method]
        stop_method = best_stop_method
    else:
        levels.final_stop = levels.stop_percent
        stop_method = "Yüzdelik"

    all_targets = {
        "ATR": levels.target_atr,
        "Direnç": levels.target_resistance,
        "Fibonacci": levels.target_fibonacci,
        "Yüzdelik": levels.target_percent,
        "Swing": levels.target_swing,
    }
    valid_targets = {key: value for key, value in all_targets.items() if value > price}
    reasonable_targets = {
        key: value
        for key, value in valid_targets.items()
        if (value - price) / price > 0.02
    }

    target_priority = ["Direnç", "ATR", "Fibonacci", "Swing", "Yüzdelik"]
    if reasonable_targets:
        best_target_method = next(
            (method for method in target_priority if method in reasonable_targets),
            min(reasonable_targets, key=reasonable_targets.get),
        )
        levels.final_target = reasonable_targets[best_target_method]
        target_method = best_target_method
    elif valid_targets:
        best_target_method = next(
            (method for method in target_priority if method in valid_targets),
            min(valid_targets, key=valid_targets.get),
        )
        levels.final_target = valid_targets[best_target_method]
        target_method = best_target_method
    else:
        levels.final_target = levels.target_percent
        target_method = "Yüzdelik"

    risk = price - levels.final_stop
    reward = levels.final_target - price
    levels.risk_pct = round(-risk / price * 100, 2)
    levels.reward_pct = round(reward / price * 100, 2)
    levels.risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0
    levels.method_used = f"Stop: {stop_method} | Hedef: {target_method}"

    stop_values = [value for value in valid_stops.values()]
    if len(stop_values) >= 3:
        std = np.std(stop_values) / price * 100
        if std < 2:
            levels.confidence = "confidence.high"
        elif std < 4:
            levels.confidence = "confidence.medium"
        else:
            levels.confidence = "confidence.low"
    else:
        levels.confidence = "confidence.low"
    return levels
