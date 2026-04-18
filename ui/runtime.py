from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import cast
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

from config import settings
from db.repositories.signals_repository import get_recent_signals, init_db, save_signal
from indicators import TechnicalIndicators
from signal_models import Signal, SignalType
from streamlit_utils import check_signals, send_signal_notification

TR = timezone(timedelta(hours=3))
logger = logging.getLogger(__name__)
INDEX_DATA_CACHE_VERSION = "v2"
SCAN_LOCK = threading.Lock()
PENDING_SCAN_RESULTS = {}
ACTIVE_SCAN_SESSIONS = set()


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] {background:linear-gradient(180deg,#121823,#0d1118);border-right:1px solid rgba(255,255,255,.06)}
            [data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu {display:none !important;}
            .block-container {max-width:1240px;padding-top:1.2rem;padding-bottom:2rem;}
            .stApp {background:radial-gradient(circle at top right, rgba(72,221,188,0.08), transparent 24%),linear-gradient(180deg,#0b1016 0%,#10141a 100%);}
        </style>
        """,
        unsafe_allow_html=True,
    )


def map_cached_signals(rows: list[dict]) -> list[Signal]:
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
                timestamp=timestamp,
                confidence=str(row.get("confidence", "CACHE") or "CACHE"),
            )
        )
    return mapped


def _collect_scan_result(fetcher, engine, notifier, last_scan_time=None, force_clear: bool = False):
    scan_started_at = datetime.now(TR)
    if force_clear:
        fetcher.clear_cache()
    elif last_scan_time is not None:
        age = (scan_started_at - last_scan_time).total_seconds()
        if age > 900:
            fetcher.clear_cache()

    timeframe_data = fetcher.fetch_multi_timeframe_all(
        trend_period=settings.MTF_TREND_PERIOD,
        trend_interval=settings.MTF_TREND_INTERVAL,
        trigger_period=settings.MTF_TRIGGER_PERIOD,
        trigger_interval=settings.MTF_TRIGGER_INTERVAL,
    )
    signals = engine.scan_all(timeframe_data)
    all_data = {ticker: data["trigger"] for ticker, data in timeframe_data.items() if isinstance(data, dict) and "trigger" in data}

    for signal in signals:
        save_signal(
            ticker=signal.ticker,
            signal_type=signal.signal_type.value,
            conditions=signal.reasons,
            score=signal.score,
            price=signal.price,
            stop_loss=signal.stop_loss,
            target_price=signal.target_price,
            confidence=signal.confidence,
        )

    for ticker, trigger_df in all_data.items():
        signal_type, conditions = check_signals(ticker, trigger_df)
        if signal_type:
            send_signal_notification(ticker, signal_type, conditions, notifier)

    return {"all_data": all_data, "signals": signals, "last_scan_time": scan_started_at, "error": None}


def _apply_scan_result(scan_result) -> None:
    st.session_state.all_data = scan_result["all_data"]
    st.session_state.signals = scan_result["signals"]
    st.session_state.last_scan_time = scan_result["last_scan_time"]
    st.session_state.scan_error = scan_result.get("error")
    st.session_state.scan_in_progress = False


def run_scan(force_clear: bool = False) -> None:
    result = _collect_scan_result(
        fetcher=st.session_state.data_fetcher,
        engine=st.session_state.engine,
        notifier=st.session_state.notifier,
        last_scan_time=st.session_state.get("last_scan_time"),
        force_clear=force_clear,
    )
    _apply_scan_result(result)


def _start_background_scan(force_clear: bool = False) -> bool:
    session_key = st.session_state.get("_scan_session_key")
    if not session_key:
        return False
    with SCAN_LOCK:
        if session_key in ACTIVE_SCAN_SESSIONS:
            return False
        ACTIVE_SCAN_SESSIONS.add(session_key)

    fetcher = st.session_state.data_fetcher
    engine = st.session_state.engine
    notifier = st.session_state.notifier
    last_scan_time = st.session_state.get("last_scan_time")
    st.session_state.scan_in_progress = True
    st.session_state.scan_error = None

    def worker():
        try:
            result = _collect_scan_result(fetcher, engine, notifier, last_scan_time=last_scan_time, force_clear=force_clear)
        except Exception as exc:
            result = {"all_data": {}, "signals": [], "last_scan_time": last_scan_time, "error": str(exc)}
        with SCAN_LOCK:
            PENDING_SCAN_RESULTS[session_key] = result
            ACTIVE_SCAN_SESSIONS.discard(session_key)

    threading.Thread(target=worker, daemon=True).start()
    return True


def apply_pending_scan_result() -> bool:
    session_key = st.session_state.get("_scan_session_key")
    if not session_key:
        return False
    with SCAN_LOCK:
        pending_result = PENDING_SCAN_RESULTS.pop(session_key, None)
        is_active = session_key in ACTIVE_SCAN_SESSIONS
    st.session_state.scan_in_progress = is_active
    if pending_result is None:
        return False
    if pending_result.get("error"):
        st.session_state.scan_error = pending_result["error"]
        st.session_state.scan_in_progress = False
        return True
    _apply_scan_result(pending_result)
    return True


def ensure_initial_data() -> None:
    apply_pending_scan_result()
    if st.session_state.signals:
        return
    try:
        cached = get_recent_signals(limit=len(settings.WATCHLIST))
        if cached:
            st.session_state.signals = map_cached_signals(cached)
            _start_background_scan(force_clear=False)
            return
        run_scan(force_clear=False)
        st.rerun()
    except Exception as exc:
        st.error(f"Tarama hatasi: {exc}")


def fetch_stock_news(ticker, max_results=5):
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


def prepare_streamlit_runtime() -> None:
    init_db()
    inject_styles()
    ensure_initial_data()
    apply_pending_scan_result()

    if st.session_state.get("scan_error"):
        st.error(f"Arka plan taramasi hatasi: {st.session_state.scan_error}")

    if st.session_state.auto_refresh and st.session_state.last_scan_time:
        elapsed = (datetime.now(TR) - st.session_state.last_scan_time).total_seconds()
        if elapsed >= st.session_state.refresh_interval * 60:
            run_scan()
            st.rerun()

    if st.session_state.get("scan_in_progress"):
        st.caption("Arka planda guncel tarama suruyor; sonuc hazir oldugunda ekran yenilenir.")
        time.sleep(1)
        st.rerun()
