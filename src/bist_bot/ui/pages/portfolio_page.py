from __future__ import annotations

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.ui.components.metric_block import render_metric_block
from bist_bot.ui.runtime import fetch_index_data, filter_signals, get_market_summary


def render_portfolio_page() -> None:
    all_data = st.session_state.get("all_data", {})
    signals = filter_signals(st.session_state.get("signals", []), all_data)
    summary = get_market_summary(signals, all_data)

    strong = [s for s in signals if s.score >= 40]
    buy = [s for s in signals if 10 <= s.score < 40]
    sell = [s for s in signals if s.score < 0]
    total = len(signals)
    pos_rate = round(len(strong + buy) / len(signals) * 100) if signals else 0

    st.title("Portfoy ve Piyasa Ozeti")
    st.caption(f"Son guncelleme: {st.session_state.last_scan_time.strftime('%d.%m.%Y %H:%M') if st.session_state.last_scan_time else '-'}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_block("Guclu Al", str(len(strong)), "Yuksek guvenli")
    with c2:
        render_metric_block("Al Akisi", str(len(buy)), "Pozitif momentum")
    with c3:
        render_metric_block("Sat Baskisi", str(len(sell)), "Dikkat gereken")
    with c4:
        render_metric_block("Pozitif Oran", f"{pos_rate}%", f"{total} toplam sinyal")

    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.subheader("Portfolio Pulse")
        top = strong[:5] if strong else sorted(signals, key=lambda x: x.score, reverse=True)[:5]
        if not top:
            st.info("Dashboard verisi icin once tarama yapin.")
        else:
            for signal in top:
                name = settings.TICKER_NAMES.get(signal.ticker, signal.ticker)
                st.markdown(
                    f"**{signal.ticker.replace('.IS','')}** - {name}  \n"
                    f"{signal.signal_type.value} | Fiyat: ₺{signal.price:.2f} | Skor: {signal.score:+.0f}"
                )
                st.divider()
    with right:
        st.subheader("Endeks Kartlari")
        index_data = fetch_index_data()
        for name, data in index_data.items():
            change = data.get("change_pct", 0.0)
            render_metric_block(name, f"{data.get('value', 0.0):,.2f}", f"{change:+.2f}%")

    st.subheader("Canli Notlar")
    avg_rsi = summary.get("avg_rsi", 50)
    analyzed = summary.get("total_analyzed", len(settings.WATCHLIST))
    notes = [
        f"Tarama kapsami: {analyzed} hisse.",
        f"Ortalama RSI: {avg_rsi:.1f}.",
        f"Pozitif sinyal orani: %{pos_rate}.",
    ]
    for note in notes:
        st.markdown(f"- {note}")
