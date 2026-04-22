from __future__ import annotations

import streamlit as st

from bist_bot.locales import get_message
from bist_bot.ui.components.metric_block import render_metric_block
from bist_bot.ui.runtime import api_request


def render_overview_page() -> None:
    st.title(get_message("ui.overview_title"))

    try:
        stats_response = api_request("GET", "/api/stats")
        signals_response = api_request("GET", "/api/signals/history", params={"limit": 20})
    except Exception as exc:
        st.warning(f"{get_message('ui.api_data_failed')}: {exc}")
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
        render_metric_block(get_message("ui.total_signals"), str(total_signals), get_message("ui.signals_over_time"))
    with c2:
        render_metric_block(get_message("ui.trades_completed"), str(completed), get_message("ui.trade_result_known"))
    with c3:
        render_metric_block(get_message("ui.profitable"), str(profitable), get_message("ui.profit_made"))
    with c4:
        render_metric_block(get_message("ui.win_rate"), f"%{win_rate:.1f}", f"{get_message('ui.avg_profit')}: %{avg_profit:.1f}")

    st.subheader(get_message("ui.recent_signals"))
    if not signals_payload:
        st.info(get_message("ui.no_signals_yet"))
    else:
        cols = st.columns([1, 1, 1, 1, 1, 1, 1])
        headers = [
            get_message("ui.ticker"),
            get_message("ui.type"),
            get_message("ui.price"),
            get_message("ui.lot"),
            get_message("ui.score"),
            get_message("ui.status"),
            get_message("ui.date"),
        ]
        for col, header in zip(cols, headers):
            col.markdown(f"**{header}**")

        for sig in signals_payload[:10]:
            cols = st.columns([1, 1, 1, 1, 1, 1, 1])
            cols[0].markdown(f"`{sig.get('ticker', '').replace('.IS', '')}`")
            cols[1].markdown(sig.get("signal_type", ""))
            cols[2].markdown(f"₺{sig.get('price', 0):.2f}")
            cols[3].markdown(str(sig.get("position_size", "-")))
            cols[4].markdown(f"{sig.get('score', 0):+.0f}")
            cols[5].markdown(sig.get("outcome", get_message("ui.pending")))
            cols[6].markdown(sig.get("timestamp", "")[:10])
