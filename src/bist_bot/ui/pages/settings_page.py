from __future__ import annotations

import streamlit as st

from bist_bot.config import store as config_store
from bist_bot.config.settings import settings
from bist_bot.ui.components.app_shell import (
    mask_secret,
    render_html_panel,
    render_page_hero,
    render_section_title,
)
from bist_bot.ui.runtime import request_scan


def render_settings_page() -> None:
    render_page_hero(
        "Settings",
        "Unified controls for scan cadence, indicators and alert routing",
        "Settings ekranini kart bazli bir control room yapisina tasidim. Tipografi, spacing, input ve CTA stilleri premium koyu tema cizgisinde birlestirildi.",
        badges=["Masked secrets", "Reusable cards", "Responsive controls"],
    )

    runtime_left, runtime_right = st.columns([1, 1], gap="large")
    with runtime_left:
        render_section_title("Runtime", "Refresh and notification behavior")
        st.session_state.auto_refresh = st.toggle(
            "Otomatik yenile", value=st.session_state.auto_refresh
        )
        st.session_state.refresh_interval = st.select_slider(
            "Tarama araligi (dk)",
            options=[1, 3, 5, 10, 15],
            value=st.session_state.refresh_interval,
        )
        st.session_state.notify_min_score = st.slider(
            "Bildirim min skor", 0, 100, st.session_state.notify_min_score
        )

    with runtime_right:
        tg_ready = bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
        token_preview = mask_secret(getattr(settings, "TELEGRAM_BOT_TOKEN", ""))
        chat_preview = mask_secret(getattr(settings, "TELEGRAM_CHAT_ID", ""), prefix=3, suffix=2)
        render_section_title("Alert routing", "Secrets stay masked")
        render_html_panel(
            (
                "<div class='bb-list'>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Bot token</div><div class='bb-note-strong'>{token_preview}</div></div></div>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Chat id</div><div class='bb-note-strong'>{chat_preview}</div></div></div>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Environment state</div><div class='bb-note-strong'>{'Ready' if tg_ready else 'Missing env values'}</div></div></div>"
                "</div>"
            ),
            accent="positive" if tg_ready else "danger",
        )
        st.session_state.notify_telegram = st.toggle(
            "Telegram bildirimi",
            value=st.session_state.notify_telegram,
            disabled=not tg_ready,
        )

    render_section_title("Indicator model", "Trading thresholds")
    i1, i2 = st.columns(2, gap="large")
    with i1:
        st.session_state.ind_rsi_period = st.slider(
            "RSI Periyot", 5, 30, st.session_state.ind_rsi_period
        )
        st.session_state.ind_rsi_oversold = st.slider(
            "RSI Asiri Satim", 10, 40, st.session_state.ind_rsi_oversold
        )
        st.session_state.ind_sma_fast = st.slider("SMA Hizli", 5, 30, st.session_state.ind_sma_fast)
        st.session_state.ind_ema_fast = st.slider("EMA Hizli", 5, 30, st.session_state.ind_ema_fast)
    with i2:
        st.session_state.ind_rsi_overbought = st.slider(
            "RSI Asiri Alim", 60, 90, st.session_state.ind_rsi_overbought
        )
        st.session_state.ind_sma_slow = st.slider(
            "SMA Yavas", 20, 100, st.session_state.ind_sma_slow
        )
        st.session_state.ind_ema_slow = st.slider(
            "EMA Yavas", 20, 100, st.session_state.ind_ema_slow
        )
        st.session_state.ind_adx_threshold = st.slider(
            "ADX Esigi", 10, 40, st.session_state.ind_adx_threshold
        )

    render_html_panel(
        "<div class='bb-note'>Telegram secrets are read only from environment variables or .env files. The UI shows masked previews only and never writes token values back to storage.</div>"
    )

    c_save, c_reset = st.columns(2)
    with c_save:
        if st.button("Kaydet ve taramayi yenile", use_container_width=True, type="primary"):
            user_settings = config_store.load_settings()
            user_settings["indicator"] = {
                "rsi_period": st.session_state.ind_rsi_period,
                "rsi_oversold": st.session_state.ind_rsi_oversold,
                "rsi_overbought": st.session_state.ind_rsi_overbought,
                "sma_fast": st.session_state.ind_sma_fast,
                "sma_slow": st.session_state.ind_sma_slow,
                "ema_fast": st.session_state.ind_ema_fast,
                "ema_slow": st.session_state.ind_ema_slow,
                "macd_fast": settings.MACD_FAST,
                "macd_slow": settings.MACD_SLOW,
                "macd_signal": settings.MACD_SIGNAL,
                "bb_period": settings.BOLLINGER_PERIOD,
                "bb_std": settings.BOLLINGER_STD,
                "adx_threshold": st.session_state.ind_adx_threshold,
            }
            user_settings["telegram"] = {
                "bot_token": "",
                "chat_id": "",
                "notify_min_score": st.session_state.notify_min_score,
                "enabled": st.session_state.notify_telegram,
            }
            user_settings["scan"] = {
                "auto_refresh": st.session_state.auto_refresh,
                "refresh_interval": st.session_state.refresh_interval,
                "min_score_filter": st.session_state.min_score_filter,
                "rsi_min_filter": st.session_state.rsi_min_filter,
                "rsi_max_filter": st.session_state.rsi_max_filter,
                "vol_ratio_filter": st.session_state.vol_ratio_filter,
            }
            config_store.save_settings(user_settings)
            if request_scan():
                st.success("Ayarlar kaydedildi.")
            else:
                st.info("Ayarlar kaydedildi. Tarama icin cooldown suresinin bitmesi bekleniyor.")
    with c_reset:
        if st.button("Varsayilanlara don", use_container_width=True):
            config_store.reset_settings()
            for key in list(st.session_state.keys()):
                key_str = key if isinstance(key, str) else ""
                if key_str.startswith("ind_") or key in {
                    "notify_min_score",
                    "notify_telegram",
                    "auto_refresh",
                    "refresh_interval",
                    "min_score_filter",
                    "rsi_min_filter",
                    "rsi_max_filter",
                    "vol_ratio_filter",
                    "_initialized",
                }:
                    del st.session_state[key]
            st.rerun()
