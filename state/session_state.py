from __future__ import annotations

import uuid

import streamlit as st

from config import settings
from config.settings import settings as global_settings
import config_store
from dependencies import build_app_container

DEFAULT_CONTAINER = build_app_container()


def init_session_state(container=None) -> None:
    if "_initialized" in st.session_state:
        return

    runtime_container = container or DEFAULT_CONTAINER
    defaults = {
        "data_fetcher": runtime_container.fetcher,
        "engine": runtime_container.engine,
        "notifier": runtime_container.notifier,
        "signals": [],
        "all_data": {},
        "auto_refresh": False,
        "refresh_interval": 5,
        "min_score_filter": -100,
        "rsi_min_filter": 0,
        "rsi_max_filter": 100,
        "vol_ratio_filter": 0.0,
        "notify_min_score": 30,
        "notify_telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
        "deploy_confirmed": False,
        "last_scan_time": None,
        "scan_in_progress": False,
        "scan_error": None,
        "current_view": "portfolio",
        "selected_ticker": settings.WATCHLIST[0],
        "analysis_period": "6mo",
        "_scan_session_key": uuid.uuid4().hex,
    }
    for key, value in defaults.items():
        st.session_state[key] = value

    stored = config_store.load_settings()
    ind = stored.get("indicator", {})
    from config.settings import DEFAULT_SETTINGS
    defaults_ind = DEFAULT_SETTINGS["indicator"]
    st.session_state["ind_rsi_period"] = ind.get("rsi_period", defaults_ind["rsi_period"])
    st.session_state["ind_rsi_oversold"] = ind.get("rsi_oversold", defaults_ind["rsi_oversold"])
    st.session_state["ind_rsi_overbought"] = ind.get("rsi_overbought", defaults_ind["rsi_overbought"])
    st.session_state["ind_sma_fast"] = ind.get("sma_fast", defaults_ind["sma_fast"])
    st.session_state["ind_sma_slow"] = ind.get("sma_slow", defaults_ind["sma_slow"])
    st.session_state["ind_ema_fast"] = ind.get("ema_fast", defaults_ind["ema_fast"])
    st.session_state["ind_ema_slow"] = ind.get("ema_slow", defaults_ind["ema_slow"])
    st.session_state["ind_macd_fast"] = ind.get("macd_fast", defaults_ind["macd_fast"])
    st.session_state["ind_macd_slow"] = ind.get("macd_slow", defaults_ind["macd_slow"])
    st.session_state["ind_macd_signal"] = ind.get("macd_signal", defaults_ind["macd_signal"])
    st.session_state["ind_bb_period"] = ind.get("bb_period", defaults_ind["bb_period"])
    st.session_state["ind_bb_std"] = float(ind.get("bb_std", defaults_ind["bb_std"]))
    st.session_state["ind_adx_threshold"] = ind.get("adx_threshold", defaults_ind["adx_threshold"])

    tg = stored.get("telegram", {})
    tg_defaults = DEFAULT_SETTINGS["telegram"]
    st.session_state["tg_token_input"] = settings.TELEGRAM_BOT_TOKEN or tg_defaults["bot_token"]
    st.session_state["tg_chat_input"] = settings.TELEGRAM_CHAT_ID or tg_defaults["chat_id"]
    st.session_state["notify_min_score"] = tg.get("notify_min_score", tg_defaults["notify_min_score"])
    st.session_state["notify_telegram"] = bool(
        tg.get("enabled", tg_defaults["enabled"])
        and settings.TELEGRAM_BOT_TOKEN
        and settings.TELEGRAM_CHAT_ID
    )

    scan = stored.get("scan", {})
    scan_defaults = DEFAULT_SETTINGS["scan"]
    st.session_state["auto_refresh"] = scan.get("auto_refresh", scan_defaults["auto_refresh"])
    st.session_state["refresh_interval"] = scan.get("refresh_interval", scan_defaults["refresh_interval"])
    st.session_state["min_score_filter"] = scan.get("min_score_filter", scan_defaults["min_score_filter"])
    st.session_state["rsi_min_filter"] = scan.get("rsi_min_filter", scan_defaults["rsi_min_filter"])
    st.session_state["rsi_max_filter"] = scan.get("rsi_max_filter", scan_defaults["rsi_max_filter"])
    st.session_state["vol_ratio_filter"] = scan.get("vol_ratio_filter", scan_defaults["vol_ratio_filter"])

    st.session_state["_initialized"] = True
