"""Gun-ici seans metrikleri: dip-toparlanma, sektor goreceli guc, breadth, hacim temposu.

2026-09-17 gozleminden dogdu: bankalar +%7 giderken ~10 kucuk hisse taban
kilitliydi, XU100 gun ici -%1.6 dipten +%0.94 toparladi; botun gunluk-trend
metrikleri bu tepki gununu goremedi.

Tum fonksiyonlar saf ve deterministiktir (network yok, `now()` yok;
`now_tr` disaridan verilir). Eksik veri -> None alanlar / no-op donus.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from bist_bot.market_calendar import TR


@dataclass(frozen=True)
class SessionStats:
    """Tek hissenin gun-ici seans olcumu (TR gun bazli)."""

    day_change_pct: float | None
    range_position: float | None
    dip_pct: float | None
    recovery_pct: float | None
    volume_pace: float | None
    limited_down: bool
    limited_up: bool


def today_slice(trigger_df: pd.DataFrame | None, now_tr: datetime) -> pd.DataFrame:
    """Trigger cerceveden `now_tr` tarihli (TR) barlari dondur."""
    if trigger_df is None or getattr(trigger_df, "empty", True):
        return pd.DataFrame()
    idx = trigger_df.index
    if isinstance(idx, pd.DatetimeIndex):
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        try:
            mask = idx.tz_convert(TR).date == now_tr.date()
        except Exception:
            return trigger_df.tail(24)
        return trigger_df[mask]
    return trigger_df.tail(24)


def _prev_daily_close(daily_df: pd.DataFrame | None, now_tr: datetime) -> float | None:
    if daily_df is None or getattr(daily_df, "empty", True) or "close" not in daily_df.columns:
        return None
    closes = pd.to_numeric(daily_df["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return float(closes.iloc[-1]) if len(closes) == 1 else None
    try:
        last_ts = pd.Timestamp(daily_df.index[-1])
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        is_today = last_ts.tz_convert(TR).date() == now_tr.date()
    except Exception:
        is_today = True
    pos = -2 if (is_today and len(closes) >= 2) else -1
    try:
        return float(closes.iloc[pos])
    except Exception:
        return None


def session_stats(
    trigger_df: pd.DataFrame | None,
    daily_df: pd.DataFrame | None,
    now_tr: datetime,
    *,
    avg_vol_lookback: int = 20,
    limit_pct: float = 9.5,
) -> SessionStats:
    """Gun-ici seans istatistiklerini hesapla; veri yoksa None alanlar."""
    day = today_slice(trigger_df, now_tr)
    prev_close = _prev_daily_close(daily_df, now_tr)

    day_change: float | None = None
    range_pos: float | None = None
    dip: float | None = None
    recovery: float | None = None
    pace: float | None = None

    last_px: float | None = None
    if len(day):
        try:
            o = float(day["open"].iloc[0])
            h = float(day["high"].max())
            day_low = float(day["low"].min())
            last_px = float(day["close"].iloc[-1])
            if o > 0:
                dip = (day_low / o - 1.0) * 100.0
            if day_low > 0:
                recovery = (last_px / day_low - 1.0) * 100.0
            width = h - day_low
            if width > 0:
                range_pos = min(1.0, max(0.0, (last_px - day_low) / width))
        except Exception:
            last_px = None

    if last_px is not None and prev_close is not None and prev_close > 0:
        day_change = (last_px / prev_close - 1.0) * 100.0
    elif daily_df is not None and getattr(daily_df, "empty", True) is False:
        try:
            closes = pd.to_numeric(daily_df["close"], errors="coerce").dropna()
            if len(closes) >= 2 and float(closes.iloc[-2]) > 0:
                day_change = (float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1.0) * 100.0
        except Exception:
            day_change = None

    if len(day) and daily_df is not None and getattr(daily_df, "empty", True) is False:
        try:
            vols = pd.to_numeric(daily_df["volume"], errors="coerce").dropna()
            hist = vols.iloc[:-1].tail(max(avg_vol_lookback, 1)) if len(vols) > 1 else vols
            avg_daily = float(hist.mean()) if len(hist) else 0.0
            elapsed_min = (now_tr.hour * 60 + now_tr.minute) - (10 * 60)
            frac = min(1.0, max(0.05, elapsed_min / 480.0))
            expected = avg_daily * frac
            cumvol = float(pd.to_numeric(day["volume"], errors="coerce").sum())
            if expected > 0:
                pace = cumvol / expected
        except Exception:
            pace = None

    lim = abs(float(limit_pct))
    return SessionStats(
        day_change_pct=day_change,
        range_position=range_pos,
        dip_pct=dip,
        recovery_pct=recovery,
        volume_pace=pace,
        limited_down=day_change is not None and day_change <= -lim,
        limited_up=day_change is not None and day_change >= lim,
    )


def universe_breadth(day_changes: Mapping[str, float]) -> dict[str, float]:
    """Evren geneli yukselis yayilimi: n, adv_pct, median, p25, p75."""
    vals = sorted(float(v) for v in day_changes.values() if v is not None)
    n = len(vals)
    if not n:
        return {"n": 0, "adv_pct": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0}

    def _pct(vals: list[float], pct: float) -> float:
        if not vals:
            return 0.0
        if len(vals) == 1:
            return float(vals[0])
        rank = pct / 100.0 * (len(vals) - 1)
        lo = int(rank)
        hi = min(lo + 1, len(vals) - 1)
        frac = rank - lo
        return float(vals[lo] * (1.0 - frac) + vals[hi] * frac)

    adv = sum(1 for v in vals if v > 0)
    return {
        "n": n,
        "adv_pct": adv / n * 100.0,
        "median": _pct(vals, 50.0),
        "p25": _pct(vals, 25.0),
        "p75": _pct(vals, 75.0),
    }


def sector_medians(
    day_changes: Mapping[str, float], sector_map: Mapping[str, str]
) -> dict[str, float]:
    """Sektor bazinda gunluk degisim medyanlari; eslesmeyenler DIGER kovasinda."""
    buckets: dict[str, list[float]] = {}
    for ticker, ch in day_changes.items():
        if ch is None:
            continue
        buckets.setdefault(sector_map.get(ticker, "DIGER"), []).append(float(ch))
    out: dict[str, float] = {}
    for sec, vals in buckets.items():
        vals.sort()
        mid = len(vals) // 2
        if len(vals) % 2:
            out[sec] = float(vals[mid])
        else:
            out[sec] = float((vals[mid - 1] + vals[mid]) / 2.0)
    return out


def apply_session_adjustment(
    *,
    params: Any,
    ticker: str,
    stats: SessionStats,
    sector_rel: float | None,
    breadth_adv_pct: float | None,
    score: float,
) -> tuple[float, list[str], bool]:
    """Seans-metrik ayarlamasi: (puan_deltasi, gerekceler, bloklandi_mi).

    Yalnizca long adaylara (score > 0) uygulanir. Taban kilitli hissede alim
    engellenir (cikisi yok). Toplam delta cap'lenir.
    """
    _ = ticker
    if not getattr(params, "session_adj_enabled", True):
        return 0.0, [], False
    if score <= 0:
        return 0.0, [], False

    delta = 0.0
    reasons: list[str] = []

    if getattr(params, "session_limit_down_block", True) and stats.limited_down:
        ch = stats.day_change_pct if stats.day_change_pct is not None else float("nan")
        return 0.0, [f"Taban kilitli ({ch:.1f}%) → cikis yok, alim engellendi"], True

    if stats.limited_up:
        pen = float(getattr(params, "session_limit_up_penalty", 6.0))
        delta -= pen
        reasons.append(f"Tavan bolgede ({stats.day_change_pct:.1f}%) → kovalamaca cezasi -{pen:g}")

    rp = stats.range_position
    rec = stats.recovery_pct
    if (
        rp is not None
        and rec is not None
        and rp >= float(getattr(params, "session_range_pos_min", 0.8))
        and rec >= float(getattr(params, "session_recovery_min_pct", 2.0))
    ):
        bonus = float(getattr(params, "session_recovery_bonus", 4.0))
        delta += bonus
        reasons.append(f"Gun-ici toparlanma (aralik %{rp * 100:.0f}, +{rec:.1f}%) → +{bonus:g}")

    if sector_rel is not None:
        thr = float(getattr(params, "session_rel_threshold", 2.0))
        bonus = float(getattr(params, "session_rel_bonus", 3.0))
        if sector_rel >= thr:
            delta += bonus
            reasons.append(f"Sektorune gore guclu (+{sector_rel:.1f} puan) → +{bonus:g}")
        elif sector_rel <= -thr:
            delta -= bonus
            reasons.append(f"Sektor gerisinde ({sector_rel:.1f} puan) → -{bonus:g}")

    if stats.volume_pace is not None:
        bonus = float(getattr(params, "session_pace_bonus", 2.0))
        if stats.volume_pace >= float(getattr(params, "session_pace_min", 1.5)):
            delta += bonus
            reasons.append(f"Hacim temposu yuksek ({stats.volume_pace:.1f}x) → +{bonus:g}")
        elif stats.volume_pace <= 0.5:
            delta -= bonus
            reasons.append(f"Hacim temposu zayif ({stats.volume_pace:.1f}x) → -{bonus:g}")

    if breadth_adv_pct is not None and breadth_adv_pct < float(
        getattr(params, "session_breadth_min_pct", 40.0)
    ):
        pen = float(getattr(params, "session_breadth_penalty", 4.0))
        delta -= pen
        reasons.append(f"Piyasa geneli zayif (yukselen %{breadth_adv_pct:.0f}) → -{pen:g}")

    cap_bonus = float(getattr(params, "session_max_bonus", 8.0))
    cap_pen = float(getattr(params, "session_max_penalty", 8.0))
    delta = max(-cap_pen, min(cap_bonus, delta))
    return delta, reasons, False
