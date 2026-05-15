from __future__ import annotations

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.ui.components.chart_widget import plot_candlestick, render_chart
from bist_bot.ui.runtime import api_request
from bist_bot.ui.session_cooldown import consume_cooldown


def render_analyze_page() -> None:
    st.title("Tekil Analiz")

    col1, _col2 = st.columns([1, 3])
    with col1:
        ticker_input = st.text_input("Hisse (THYAO.IS)", value="THYAO.IS").strip().upper()
        analyze_btn = st.button("Analiz Et", type="primary", use_container_width=True)

    if not ticker_input.endswith(".IS"):
        ticker_input = f"{ticker_input}.IS"

    if analyze_btn:
        allowed, remaining = consume_cooldown(
            st.session_state,
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
        return

    snapshot = data.get("snapshot", {})
    signal = data.get("signal", {})
    price_data = data.get("price_data", [])

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Fiyat", f"₺{snapshot.get('close', 0):.2f}")
    with c2:
        st.metric("RSI", f"{snapshot.get('rsi', 0):.1f}")
    with c3:
        st.metric("SMA", f"{snapshot.get('sma_20', 0):.1f}")
    with c4:
        st.metric("Trend", snapshot.get("trend", "N/A"))

    st.subheader("Grafik")
    if price_data:
        import pandas as pd

        df = pd.DataFrame(price_data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        if "open" in df.columns and "close" in df.columns:
            fig = plot_candlestick(df, ticker_input)
            render_chart(fig, "candlestick_main")
        else:
            st.warning("Grafik verisi yok.")
    else:
        st.info("Fiyat verisi mevcut degil.")

    st.subheader("Sinyal ve Seviyeler")
    sig_type = signal.get("type", "N/A")
    sig_score = signal.get("score", 0)
    stop_loss = signal.get("stop_loss", 0)
    target = signal.get("target", 0)
    position_size = signal.get("position_size")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Sinyal", sig_type, f"Skor: {sig_score:+.0f}")
    with c2:
        st.metric("Zarar Durdrm", f"₺{stop_loss:.2f}" if stop_loss else "-")
    with c3:
        st.metric("Hedef", f"₺{target:.2f}" if target else "-")
    with c4:
        st.metric("Lot", str(position_size) if position_size is not None else "-")

    reasons = signal.get("reasons", [])
    if reasons:
        st.subheader("Analiz Nedenleri")
        for reason in reasons:
            st.markdown(f"- {reason}")
