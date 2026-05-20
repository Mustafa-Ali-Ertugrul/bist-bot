from __future__ import annotations

import html
from collections.abc import MutableMapping
from typing import cast

import pandas as pd
import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.ui.components.app_shell import (
    render_html_panel,
    render_page_hero,
    render_section_title,
)
from bist_bot.ui.components.chart_widget import (
    plot_candlestick,
    plot_rsi,
    plot_volume,
    render_chart,
)
from bist_bot.ui.components.metric_block import render_metric_block
from bist_bot.ui.runtime import api_request
from bist_bot.ui.session_cooldown import consume_cooldown


def _signal_tone(score: float) -> str:
    if score >= settings.BUY_THRESHOLD:
        return "positive"
    if score >= settings.WEAK_BUY_THRESHOLD:
        return "positive"
    if score <= settings.WEAK_SELL_THRESHOLD:
        return "danger"
    return "neutral"


def _badge_class_for_tone(tone: str) -> str:
    return f"bb-badge bb-badge-{tone}"


def _is_buy_side_score(score: float) -> bool:
    return score >= settings.WEAK_BUY_THRESHOLD


def _ticker_option_label(ticker: str) -> str:
    symbol = ticker.replace(".IS", "")
    name = settings.TICKER_NAMES.get(ticker)
    if not name or name == ticker:
        return symbol
    return f"{symbol} - {name}"


def render_analyze_page() -> None:
    render_page_hero(
        "Analiz",
        "Tek varlık için koyu trading terminali stilinde araştırma paneli",
        "Analysis ekranini premium mobil fintech mockup diline yaklastirdim. Arama, snapshot, chart ve level kartlari artik ayni tasarim sistemi icinde calisiyor.",
        badges=["Mum Grafiği + RSI", "Sinyal Nedenleri", "Mobil Öncelikli Düzen"],
    )

    render_section_title("Varlık Arama", "Yeni bir analiz isteği çalıştırın")
    c1, c2 = st.columns([1.5, 1])
    with c1:
        ticker_options = list(settings.WATCHLIST or settings.DEFAULT_BIST100_WATCHLIST)
        default_ticker = "THYAO.IS"
        default_index = ticker_options.index(default_ticker) if default_ticker in ticker_options else 0
        ticker_input = st.selectbox(
            "Hisse",
            options=ticker_options,
            index=default_index,
            format_func=_ticker_option_label,
            placeholder="Sembol veya sirket adi ara",
        )
    with c2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        analyze_btn = st.button("Varlığı Analiz Et", type="primary", use_container_width=True)

    ticker_input = str(ticker_input or default_ticker).strip().upper()
    if not ticker_input.endswith(".IS"):
        ticker_input = f"{ticker_input}.IS"

    if analyze_btn:
        cooldown_state: MutableMapping[str, float] = cast(
            MutableMapping[str, float], st.session_state
        )
        allowed, remaining = consume_cooldown(
            cooldown_state,
            action="analyze",
            cooldown_seconds=float(getattr(settings, "STREAMLIT_ANALYZE_COOLDOWN_SECONDS", 4.0)),
        )
        if not allowed:
            st.warning(f"Cok sik istek gonderildi, birkac saniye bekleyin. ({remaining:.1f}s)")
            return
        try:
            response = api_request("GET", f"/api/analyze/{ticker_input}")
        except Exception as exc:
            st.error(f"API hatasi: {exc}")
            return

        if not response.ok:
            st.error(f"Analiz basarisiz: {response.json().get('message', 'Bilinmeyen hata')}")
            return

        data = response.json()
        if data.get("status") != "ok":
            st.error(f"Sonuc hatasi: {data.get('message', '')}")
            return

        st.session_state["last_analyzed_ticker"] = ticker_input
        st.session_state["last_analyze_result"] = data

    data = st.session_state.get("last_analyze_result")
    if st.session_state.get("last_analyzed_ticker") != ticker_input or not data:
        render_html_panel(
            "<div class='bb-note'>Premium araştırma panelini doldurmak için bir BIST hisse sembolü analiz ederek başlayın.</div>"
        )
        return

    snapshot = data.get("snapshot", {})
    signal = data.get("signal", {})
    price_data = data.get("price_data", [])

    signal_score = float(signal.get("score", 0) or 0)
    signal_type = str(signal.get("type", "N/A"))
    trend = str(snapshot.get("trend", "N/A"))
    signal_tone = _signal_tone(signal_score)
    verdict_badge = _badge_class_for_tone(signal_tone)

    headline_html = (
        "<div style='display:flex;justify-content:space-between;gap:14px;align-items:flex-start;'>"
        "<div>"
        f"<div class='bb-label'>Aktif varlık</div><div style='font-size:34px;font-weight:900;letter-spacing:-.06em;color:var(--bb-text);margin-top:8px;'>{html.escape(ticker_input.replace('.IS', ''))}</div>"
        f"<div class='bb-note'>Trend {html.escape(trend)} • Son kapanış TL{float(snapshot.get('close', 0) or 0):.2f}</div>"
        "</div>"
        f"<span class='{verdict_badge}'>{html.escape(signal_type)}</span>"
        "</div>"
    )
    render_html_panel(
        headline_html,
        accent=signal_tone,
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_metric_block(
            "Son fiyat",
            f"TL{float(snapshot.get('close', 0) or 0):.2f}",
            "Kapanış değeri",
        )
    with m2:
        render_metric_block(
            "RSI", f"{float(snapshot.get('rsi', 0) or 0):.1f}", "Momentum osilatörü"
        )
    with m3:
        render_metric_block(
            "SMA 20", f"{float(snapshot.get('sma_20', 0) or 0):.1f}", "Trend taban çizgisi"
        )
    with m4:
        render_metric_block(
            "Sinyal skoru",
            f"{signal_score:+.0f}",
            signal_type,
            accent=signal_tone,
        )

    if price_data:
        df = pd.DataFrame(price_data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df_ind = TechnicalIndicators().add_all(df.copy())

        render_section_title("Teknik Görünüm", "Fiyat yapısı ve momentum")
        render_chart(plot_candlestick(df_ind, ticker_input), "analysis_candlestick_main")

        c_left, c_right = st.columns([1, 1], gap="large")
        with c_left:
            if "volume" in df_ind.columns:
                render_chart(plot_volume(df_ind), "analysis_volume")
        with c_right:
            if "rsi" in df_ind.columns:
                render_chart(plot_rsi(df_ind), "analysis_rsi")
    else:
        st.info("Fiyat verisi mevcut degil.")

    render_section_title("İşlem Planı", "Kritik seviyeler")
    p1, p2 = st.columns([1, 1], gap="large")
    with p1:
        if _is_buy_side_score(signal_score):
            plan_html = (
                "<div class='bb-list'>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Sinyal</div><div class='bb-note-strong'>{html.escape(signal_type)}</div></div><div class='bb-note-strong'>{signal_score:+.0f}</div></div>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Stop loss</div><div class='bb-note-strong bb-text-danger'>TL{float(signal.get('stop_loss', 0) or 0):.2f}</div></div></div>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Hedef</div><div class='bb-note-strong bb-text-positive'>TL{float(signal.get('target', 0) or 0):.2f}</div></div></div>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Pozisyon büyüklüğü</div><div class='bb-note-strong'>{html.escape(str(signal.get('position_size', '-')))}</div></div></div>"
                "</div>"
            )
        else:
            plan_html = (
                "<div class='bb-list'>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Sinyal</div><div class='bb-note-strong'>{html.escape(signal_type)}</div></div><div class='bb-note-strong'>{signal_score:+.0f}</div></div>"
                "<div class='bb-note'>Alış yönlü sinyal olmadığı için alış işlem planı gizlendi.</div>"
                "</div>"
            )
        render_html_panel(plan_html, accent=signal_tone)
    with p2:
        reasons = signal.get("reasons", [])
        reason_rows = "".join(
            f"<div class='bb-list-row'><div class='bb-list-row-subtitle'>{html.escape(str(reason))}</div></div>"
            for reason in reasons
        )
        reasons_html = reason_rows or "<div class='bb-note'>Analiz nedeni döndürülmedi.</div>"
        render_html_panel(
            "<div class='bb-section-caption'>Model gerekçesi</div>"
            f"<div class='bb-list' style='margin-top:12px;'>{reasons_html}</div>"
        )
