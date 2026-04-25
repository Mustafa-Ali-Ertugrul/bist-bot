from __future__ import annotations

import streamlit as st

from bist_bot.locales import get_message
from bist_bot.ui.components.chart_widget import plot_candlestick
from bist_bot.ui.components.signal_card import render_signal_card
from bist_bot.ui.runtime import filter_signals


def render_signals_page() -> None:
    all_data = st.session_state.get("all_data", {})
    signals = filter_signals(st.session_state.get("signals", []), all_data)

    st.title(get_message("ui.signals_title"))
    f1, f2, f3 = st.columns(3)
    with f1:
        st.session_state.min_score_filter = st.slider(
            get_message("ui.min_score"), -100, 100, st.session_state.min_score_filter
        )
    with f2:
        st.session_state.rsi_min_filter = st.slider(
            get_message("ui.rsi_min"), 0, 100, st.session_state.rsi_min_filter
        )
    with f3:
        st.session_state.rsi_max_filter = st.slider(
            get_message("ui.rsi_max"), 0, 100, st.session_state.rsi_max_filter
        )

    strong_tab, buy_tab, sell_tab = st.tabs(
        [
            get_message("ui.strong_buy_tab"),
            get_message("ui.buy_tab"),
            get_message("ui.sell_neutral_tab"),
        ]
    )
    with strong_tab:
        strong = sorted([s for s in signals if s.score >= 40], key=lambda s: s.score, reverse=True)
        if strong:
            for signal in strong:
                render_signal_card(signal, all_data.get(signal.ticker), plot_candlestick)
        else:
            st.info(get_message("ui.no_strong_buy"))
    with buy_tab:
        buy = sorted(
            [s for s in signals if 10 <= s.score < 40], key=lambda s: s.score, reverse=True
        )
        if buy:
            for signal in buy:
                render_signal_card(signal, all_data.get(signal.ticker), plot_candlestick)
        else:
            st.info(get_message("ui.no_buy"))
    with sell_tab:
        sell = sorted([s for s in signals if s.score < 10], key=lambda s: s.score)
        if sell:
            for signal in sell:
                render_signal_card(signal, all_data.get(signal.ticker), plot_candlestick)
        else:
            st.info(get_message("ui.no_sell"))
