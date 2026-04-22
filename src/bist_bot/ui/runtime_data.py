"""Data transformation and read-only helpers for the Streamlit runtime."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.signal_models import Signal, SignalType

TR = timezone(timedelta(hours=3))
INDEX_DATA_CACHE_VERSION = "v2"


def map_cached_signals(rows: list[dict]) -> list[Signal]:
    """Convert persisted signal rows into domain Signal objects."""
    mapped: list[Signal] = []
    for row in rows:
        raw_conditions = row.get("conditions", [])
        reasons = raw_conditions if isinstance(raw_conditions, list) else [str(raw_conditions)]
        try:
            signal_type = SignalType(row["signal_type"])
        except Exception:
            signal_type = SignalType.HOLD
        try:
            timestamp = datetime.fromisoformat(row["created_at"])
        except Exception:
            timestamp = datetime.now(TR)
        mapped.append(
            Signal(
                ticker=row["ticker"],
                signal_type=signal_type,
                score=float(row.get("score", 0.0) or 0.0),
                price=float(row.get("price", 0.0) or 0.0),
                reasons=reasons,
                stop_loss=float(row.get("stop_loss", 0.0) or 0.0),
                target_price=float(row.get("target_price", 0.0) or 0.0),
                position_size=int(row["position_size"]) if row.get("position_size") is not None else None,
                timestamp=timestamp,
                confidence=str(row.get("confidence", "CACHE") or "CACHE"),
            )
        )
    return mapped


def fetch_stock_news(ticker, max_results=5):
    """Fetch recent ticker-related news headlines from Google News RSS."""
    name = settings.TICKER_NAMES.get(ticker, ticker.replace(".IS", ""))
    all_news = []
    try:
        url = f"https://news.google.com/rss/search?q={name}+hisse+senedi&hl=tr&gl=TR&ceid=TR:tr"
        response = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        for item in items[:max_results]:
            title = item.findtext("title", "").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            if len(title) > 10:
                all_news.append({
                    "title": title,
                    "url": item.findtext("link", ""),
                    "source": "Google Haberler",
                    "published_at": item.findtext("pubDate", "")[:16],
                })
    except Exception:
        pass
    return all_news[:max_results]


def get_market_summary(signals, all_data):
    """Build aggregate market summary metrics for the portfolio view."""
    if not signals or not all_data:
        return {}
    ti = TechnicalIndicators()
    sector_data = {}
    rsi_values = []
    vol_ratios = []
    for ticker, df in all_data.items():
        try:
            df_ind = ti.add_all(df.copy())
            last = df_ind.iloc[-1]
            rsi = last.get("rsi", 50)
            vol = last.get("volume_ratio", 1.0)
            rsi_values.append(rsi)
            vol_ratios.append(vol)
            if rsi < 30:
                sector_data["Asiri Satim"] = sector_data.get("Asiri Satim", 0) + 1
            elif rsi > 70:
                sector_data["Asiri Alim"] = sector_data.get("Asiri Alim", 0) + 1
            else:
                sector_data["Notr"] = sector_data.get("Notr", 0) + 1
        except Exception:
            pass
    return {
        "sector_dist": sector_data,
        "avg_rsi": sum(rsi_values) / len(rsi_values) if rsi_values else 50,
        "avg_vol_ratio": sum(vol_ratios) / len(vol_ratios) if vol_ratios else 1.0,
        "total_analyzed": len(rsi_values),
    }


@st.cache_data(ttl=180)
def fetch_index_data(cache_version: str = INDEX_DATA_CACHE_VERSION):
    """Fetch short-lived benchmark snapshots for the dashboard header."""
    _ = cache_version
    try:
        import yfinance as yf

        tickers = {"XU100": "XU100.IS", "XU030": "XU030.IS", "USDTRY": "USDTRY=X"}
        result = {}
        for name, ticker in tickers.items():
            try:
                raw = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
                if raw is None or raw.empty:
                    result[name] = {"value": 0.0, "change_pct": 0.0}
                    continue
                raw = cast(pd.DataFrame, raw)
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                if "Close" not in raw.columns:
                    result[name] = {"value": 0.0, "change_pct": 0.0}
                    continue
                raw = raw.dropna(subset=["Close"])
                if len(raw) >= 2:
                    prev = float(raw["Close"].iloc[-2])
                    last = float(raw["Close"].iloc[-1])
                    result[name] = {"value": last, "change_pct": ((last - prev) / prev) * 100}
                elif len(raw) == 1:
                    result[name] = {"value": float(raw["Close"].iloc[-1]), "change_pct": 0.0}
                else:
                    result[name] = {"value": 0.0, "change_pct": 0.0}
            except Exception:
                result[name] = {"value": 0.0, "change_pct": 0.0}
        return result
    except Exception:
        return {}


def filter_signals(base_signals, all_data):
    """Apply UI-level signal filters using session-state thresholds."""
    filtered = [s for s in base_signals if s.score >= st.session_state.min_score_filter]
    if st.session_state.rsi_min_filter <= 0 and st.session_state.rsi_max_filter >= 100 and st.session_state.vol_ratio_filter <= 0:
        return filtered
    ti = TechnicalIndicators()
    result = []
    for signal in filtered:
        df = all_data.get(signal.ticker)
        if df is None:
            continue
        try:
            last = ti.add_all(df.copy()).iloc[-1]
            rsi = last.get("rsi", 50)
            volume_ratio = last.get("volume_ratio", 1.0)
            if st.session_state.rsi_min_filter <= rsi <= st.session_state.rsi_max_filter and volume_ratio >= st.session_state.vol_ratio_filter:
                result.append(signal)
        except Exception:
            pass
    return result
