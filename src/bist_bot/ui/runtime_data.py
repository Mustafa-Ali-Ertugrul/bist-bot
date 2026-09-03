"""Data transformation and read-only helpers for the Streamlit runtime."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405: defusedxml primary; fallback capped.
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import numpy as np
import pandas as pd
import requests
import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.signal_models import Signal, SignalType

try:  # XXE-safe RSS parsing when available (declared in requirements.txt).
    from defusedxml.ElementTree import fromstring as _rss_fromstring
except ImportError:  # pragma: no cover - fallback for minimal installs.

    def _rss_fromstring(content: bytes) -> ET.Element:
        return ET.fromstring(content)  # nosec B314: Google News RSS fallback path.


#: RSS payload cap: Google News feeds are a few KB; anything larger is rejected
#: before XML parsing (entity-expansion / billion-laughs guard).
MAX_RSS_BYTES = 512 * 1024


def _parse_rss(content: bytes) -> ET.Element:
    """Parse an RSS payload with size cap + entity-forbidding parser."""
    if len(content) > MAX_RSS_BYTES:
        raise ValueError(f"RSS payload too large ({len(content)} bytes)")
    return _rss_fromstring(content)


TR = timezone(timedelta(hours=3))
INDEX_DATA_CACHE_VERSION = "v2"


def map_cached_signals(rows: list[dict]) -> list[Signal]:
    """Convert persisted signal rows into domain Signal objects."""
    mapped: list[Signal] = []
    for row in rows:
        raw_conditions = row.get("conditions", [])
        reasons = raw_conditions if isinstance(raw_conditions, list) else [str(raw_conditions)]
        try:
            signal_type = SignalType.from_value(row["signal_type"])
        except Exception:
            signal_type = SignalType.HOLD
        try:
            timestamp = datetime.fromisoformat(
                str(row.get("created_at") or "").replace("Z", "+00:00")
            )
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
        except Exception:
            timestamp = datetime.now(UTC)
        mapped.append(
            Signal(
                ticker=row["ticker"],
                signal_type=signal_type,
                score=float(row.get("score", 0.0) or 0.0),
                price=float(row.get("price", 0.0) or 0.0),
                reasons=reasons,
                stop_loss=float(row.get("stop_loss", 0.0) or 0.0),
                target_price=float(row.get("target_price", 0.0) or 0.0),
                position_size=int(row["position_size"])
                if row.get("position_size") is not None
                else None,
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
        root = _parse_rss(response.content)
        items = root.findall(".//item")
        for item in items[:max_results]:
            title = (
                item.findtext("title", "")
                .replace("&amp;", "&")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
            )
            if len(title) > 10:
                all_news.append(
                    {
                        "title": title,
                        "url": item.findtext("link", ""),
                        "source": "Google Haberler",
                        "published_at": item.findtext("pubDate", "")[:16],
                    }
                )
    except Exception:
        pass
    return all_news[:max_results]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_bist100_news(max_results: int = 5) -> list[dict[str, str]]:
    """Fetch recent BIST100-related news headlines from Google News RSS."""
    all_news: list[dict[str, str]] = []
    try:
        query = "BIST 100 OR BIST100 OR XU100 borsa"
        url = f"https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"
        response = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = _parse_rss(response.content)
        items = root.findall(".//item")
        for item in items[:max_results]:
            title = (
                item.findtext("title", "")
                .replace("&amp;", "&")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
            )
            link = item.findtext("link", "")
            source = item.find("source")
            source_name = source.text if source is not None and source.text else "Google Haberler"
            if len(title) > 10 and link:
                all_news.append(
                    {
                        "title": title,
                        "url": link,
                        "source": source_name,
                        "published_at": item.findtext("pubDate", "")[:16],
                    }
                )
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
    total_analyzed = 0
    for _ticker, df in all_data.items():
        try:
            if df is None or df.empty:
                continue
            df_ind = ti.add_all(df.copy())
            if df_ind is None or df_ind.empty:
                continue
            total_analyzed += 1
            last = df_ind.iloc[-1]
            rsi_raw = last.get("rsi", 50)
            vol_raw = last.get("volume_ratio", 1.0)
            rsi = float(rsi_raw) if pd.notna(rsi_raw) and np.isfinite(rsi_raw) else 50.0
            vol = float(vol_raw) if pd.notna(vol_raw) and np.isfinite(vol_raw) else 1.0
            rsi_values.append(rsi)
            vol_ratios.append(vol)
            if rsi < 30:
                sector_data["Aşırı Satım"] = sector_data.get("Aşırı Satım", 0) + 1
            elif rsi > 70:
                sector_data["Aşırı Alım"] = sector_data.get("Aşırı Alım", 0) + 1
            else:
                sector_data["Notr"] = sector_data.get("Notr", 0) + 1
        except Exception:
            pass
    valid_rsi = [v for v in rsi_values if pd.notna(v) and np.isfinite(v)]
    valid_vol = [v for v in vol_ratios if pd.notna(v) and np.isfinite(v)]
    return {
        "sector_dist": sector_data,
        "avg_rsi": sum(valid_rsi) / len(valid_rsi) if valid_rsi else 50.0,
        "avg_vol_ratio": sum(valid_vol) / len(valid_vol) if valid_vol else 1.0,
        "total_analyzed": total_analyzed,
        "rsi_sample_count": len(valid_rsi),
        "volume_sample_count": len(valid_vol),
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
    if (
        st.session_state.rsi_min_filter <= 0
        and st.session_state.rsi_max_filter >= 100
        and st.session_state.vol_ratio_filter <= 0
    ):
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
            if (
                st.session_state.rsi_min_filter <= rsi <= st.session_state.rsi_max_filter
                and volume_ratio >= st.session_state.vol_ratio_filter
            ):
                result.append(signal)
        except Exception:
            pass
    return result
