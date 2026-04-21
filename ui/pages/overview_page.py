from __future__ import annotations

import streamlit as st

from ui.components.metric_block import render_metric_block
from ui.runtime import api_request


def render_overview_page() -> None:
    st.title("Genel Bakis")

    try:
        stats_response = api_request("GET", "/api/stats")
        signals_response = api_request("GET", "/api/signals/history", params={"limit": 20})
    except Exception as exc:
        st.warning(f"API verileri alinamadi: {exc}")
        return

    stats = stats_response.json().get("stats", {}) if stats_response.ok else {}
    signals_payload = signals_response.json().get("signals", []) if signals_response.ok else []

    total_signals = stats.get("total_signals", 0)
    completed = stats.get("completed", 0)
    profitable = stats.get("profitable", 0)
    win_rate = stats.get("win_rate", 0.0)
    avg_profit = stats.get("avg_profit_pct", 0.0)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_block("Toplam Sinyal", str(total_signals), "Tarih boyunca")
    with c2:
        render_metric_block("Islem Tamamlandi", str(completed), "Sonuc belli")
    with c3:
        render_metric_block("Karli", str(profitable), "Kar elde eden")
    with c4:
        render_metric_block("Win Rate", f"%{win_rate:.1f}", f"Ort. kar: %{avg_profit:.1f}")

    st.subheader("Son Sinyaller")
    if not signals_payload:
        st.info("Henuz sinyal kaydedilmemis.")
    else:
        cols = st.columns([1, 1, 1, 1, 1, 1])
        headers = ["Ticker", "Tip", "Fiyat", "Skor", "Durum", "Tarih"]
        for col, header in zip(cols, headers):
            col.markdown(f"**{header}**")

        for sig in signals_payload[:10]:
            cols = st.columns([1, 1, 1, 1, 1, 1])
            cols[0].markdown(f"`{sig.get('ticker', '').replace('.IS', '')}`")
            cols[1].markdown(sig.get("signal_type", ""))
            cols[2].markdown(f"₺{sig.get('price', 0):.2f}")
            cols[3].markdown(f"{sig.get('score', 0):+.0f}")
            cols[4].markdown(sig.get("outcome", "PENDING"))
            cols[5].markdown(sig.get("timestamp", "")[:10])