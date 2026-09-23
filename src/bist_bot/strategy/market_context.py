"""Tarama-bazlı makro piyasa bağlamı (USD/TRY, XU100) — saf fonksiyonlar.

Tüm fonksiyonlar deterministiktir: ``now()`` çağrısı yok, yalnızca verilen
DataFrame'ler okunur. Eksik/bayat veri graceful-degrade ile no-op üretir
(ceza yok, gate yok). ``MarketContext`` tarama başına bir kez kurulur
(``ScanService._build_market_context``) ve engine'e taşınır; ticker başına
yeniden fetch yapılmaz.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MarketContext:
    """Bir tarama için hazırlanmış makro bağlam.

    ``None`` alan = veri alınamadı → ilgili filtre sessizce no-op olur.
    """

    usdtry_df: pd.DataFrame | None = None
    xu100_df: pd.DataFrame | None = None


def usdtry_trend_rising(df: pd.DataFrame | None, lookback: int) -> bool:
    """USD/TRY son kapanışı SMA(lookback) üzerindeyse True döner.

    Yetersiz geçmiş (< lookback + 1 satır) veya eksik close sütunu → False
    (conservative: trend teyidi yoksa ceza uygulanmaz).
    """
    if df is None or lookback < 2:
        return False
    close = df.get("close")
    if close is None or len(df) < lookback + 1:
        return False
    series = close.astype(float).dropna()
    if len(series) < lookback + 1:
        return False
    sma = float(series.tail(lookback).mean())
    return float(series.iloc[-1]) > sma


def forex_penalty(
    *,
    params: Any,
    ticker: str,
    sector_map: Mapping[str, str],
    usdtry_df: pd.DataFrame | None,
) -> tuple[float, str | None]:
    """Yüksek döviz-riski sektöründeki long adaylar için puan cezası.

    Kural: ``forex_filter_enabled`` açık + ticker'ın sektörü
    ``forex_risk_sectors`` içinde + USD/TRY yükseliş trendindeyse
    ``forex_penalty_points`` döner; aksi hâlde ``(0.0, None)``.

    Cezayı yalnızca long adaylara uygulama kararı çağırana aittir
    (engine ``score > 0`` iken çağırır) — satış adaylarını güçlendirmez.
    """
    if not getattr(params, "forex_filter_enabled", False):
        return 0.0, None
    sector = sector_map.get(ticker)
    risk_sectors = tuple(getattr(params, "forex_risk_sectors", ()) or ())
    if not sector or sector not in risk_sectors:
        return 0.0, None
    lookback = int(getattr(params, "forex_trend_lookback", 20))
    if not usdtry_trend_rising(usdtry_df, lookback):
        return 0.0, None
    points = float(getattr(params, "forex_penalty_points", 5.0))
    if points <= 0:
        return 0.0, None
    reason = f"USD/TRY yükseliş trendinde + {sector} sektörü döviz riski → skor -{points:g} cezası"
    return points, reason
