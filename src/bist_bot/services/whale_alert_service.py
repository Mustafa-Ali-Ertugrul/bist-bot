"""Heuristic whale-activity alerts built from existing BIST scan data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.signal_models import Signal, SignalType


@dataclass(frozen=True)
class WhaleAlert:
    ticker: str
    score: int
    direction: str
    severity: str
    price: float
    change_pct: float
    volume_ratio: float
    signal_score: float
    reasons: list[str] = field(default_factory=list)
    action_note: str = "Izleme listesine al; tek basina alim-satim karari degildir."


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(result):
        return default
    return result


def _resolve_frame(raw_data: Any) -> pd.DataFrame | None:
    if isinstance(raw_data, pd.DataFrame):
        return raw_data
    if isinstance(raw_data, dict):
        trigger = raw_data.get("trigger")
        if isinstance(trigger, pd.DataFrame):
            return trigger
    return None


def _signal_map(signals: list[Signal]) -> dict[str, Signal]:
    return {signal.ticker: signal for signal in signals}


def _classify_direction(signal: Signal | None, change_pct: float, obv_trend: str) -> str:
    if signal is not None:
        if signal.signal_type in {SignalType.BUY, SignalType.STRONG_BUY, SignalType.WEAK_BUY}:
            return "Toplama izi"
        if signal.signal_type in {SignalType.SELL, SignalType.STRONG_SELL, SignalType.WEAK_SELL}:
            return "Dagitim izi"
    if change_pct >= 2.5 or obv_trend.upper() == "RISING":
        return "Toplama izi"
    if change_pct <= -2.5 or obv_trend.upper() == "FALLING":
        return "Dagitim izi"
    return "Olagandisi izleme"


def _severity(score: int) -> str:
    if score >= 80:
        return "Yuksek"
    if score >= 60:
        return "Orta"
    return "Dusuk"


def build_whale_alerts(
    all_data: dict[str, Any],
    signals: list[Signal],
    *,
    min_score: int = 45,
    limit: int = 20,
) -> list[WhaleAlert]:
    """Build explainable whale-activity candidates from scan data.

    This is deliberately heuristic. It flags unusual market behavior for human
    review; it does not infer real order-book ownership or produce trade advice.
    """
    if not all_data:
        return []

    indicators = TechnicalIndicators()
    signals_by_ticker = _signal_map(signals)
    alerts: list[WhaleAlert] = []

    for ticker, raw_data in all_data.items():
        frame = _resolve_frame(raw_data)
        if frame is None or frame.empty or len(frame) < 2:
            continue
        try:
            enriched = indicators.add_all(frame.copy())
        except Exception:
            continue
        if enriched is None or enriched.empty or len(enriched) < 2:
            continue

        last = enriched.iloc[-1]
        prev = enriched.iloc[-2]
        close = _to_float(last.get("close"), _to_float(last.get("Close")))
        prev_close = _to_float(prev.get("close"), _to_float(prev.get("Close"), close))
        if close <= 0 or prev_close <= 0:
            continue

        change_pct = ((close - prev_close) / prev_close) * 100
        volume_ratio = _to_float(last.get("volume_ratio"), 1.0)
        rsi = _to_float(last.get("rsi"), 50.0)
        adx = _to_float(last.get("adx"), 0.0)
        support = _to_float(last.get("support"), 0.0)
        resistance = _to_float(last.get("resistance"), 0.0)
        obv_trend = str(last.get("obv_trend", "FLAT") or "FLAT")
        signal = signals_by_ticker.get(ticker)
        signal_score = float(signal.score) if signal is not None else 0.0

        score = 0
        reasons: list[str] = []

        if volume_ratio >= 4.0:
            score += 35
            reasons.append(f"Hacim 20 gunluk ortalamanin {volume_ratio:.1f} kati")
        elif volume_ratio >= 2.5:
            score += 25
            reasons.append(f"Hacim ortalamanin {volume_ratio:.1f} kati")
        elif volume_ratio >= 1.7:
            score += 15
            reasons.append(f"Hacim ortalamanin ustunde: {volume_ratio:.1f}x")

        abs_change = abs(change_pct)
        if abs_change >= 5.0:
            score += 25
            reasons.append(f"Sert fiyat ayrismasi: %{change_pct:+.1f}")
        elif abs_change >= 3.0:
            score += 18
            reasons.append(f"Belirgin fiyat hareketi: %{change_pct:+.1f}")
        elif abs_change >= 1.8:
            score += 10
            reasons.append(f"Gun ici hareket dikkat cekiyor: %{change_pct:+.1f}")

        if abs(signal_score) >= 60:
            score += 22
            reasons.append(f"Mevcut model sinyali guclu: {signal_score:+.0f}")
        elif abs(signal_score) >= 35:
            score += 14
            reasons.append(f"Mevcut model sinyali destekliyor: {signal_score:+.0f}")

        if adx >= 25:
            score += 8
            reasons.append(f"Trend gucu yuksek: ADX {adx:.1f}")

        if resistance > 0 and close >= resistance * 0.99:
            score += 8
            reasons.append("Fiyat direnc bolgesine yakin")
        elif support > 0 and close <= support * 1.01:
            score += 8
            reasons.append("Fiyat destek bolgesinde hacimle izlenmeli")

        if obv_trend.upper() in {"RISING", "FALLING"}:
            score += 7
            reasons.append(f"OBV trendi: {obv_trend.lower()}")

        if rsi >= 70 or rsi <= 30:
            score += 5
            reasons.append(f"RSI uc bolgede: {rsi:.1f}")

        bounded_score = min(score, 100)
        if bounded_score < min_score:
            continue
        alerts.append(
            WhaleAlert(
                ticker=ticker,
                score=bounded_score,
                direction=_classify_direction(signal, change_pct, obv_trend),
                severity=_severity(bounded_score),
                price=close,
                change_pct=change_pct,
                volume_ratio=volume_ratio,
                signal_score=signal_score,
                reasons=reasons[:5],
            )
        )

    return sorted(alerts, key=lambda alert: alert.score, reverse=True)[:limit]
