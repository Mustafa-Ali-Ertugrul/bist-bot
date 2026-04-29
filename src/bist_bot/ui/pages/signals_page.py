from __future__ import annotations

import streamlit as st

from bist_bot.config import settings
from bist_bot.locales import get_message
from bist_bot.ui.components.app_shell import (
    render_html_panel,
    render_page_hero,
    render_section_title,
)
from bist_bot.ui.components.chart_widget import plot_candlestick
from bist_bot.ui.components.signal_card import render_signal_card
from bist_bot.ui.runtime import filter_signals


def _render_signal_group(title: str, items, all_data) -> None:
    render_section_title(title, f"{len(items)} assets")
    if not items:
        st.info(f"{title} icin uygun sinyal yok.")
        return
    for signal in items:
        render_signal_card(signal, all_data.get(signal.ticker), plot_candlestick)


def render_signals_page() -> None:
    all_data = st.session_state.get("all_data", {})
    signals = filter_signals(st.session_state.get("signals", []), all_data)

    strong = sorted(
        [s for s in signals if s.score >= settings.STRONG_BUY_THRESHOLD],
        key=lambda s: s.score,
        reverse=True,
    )
    buy = sorted(
        [
            s
            for s in signals
            if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD
        ],
        key=lambda s: s.score,
        reverse=True,
    )
    watch = sorted(
        [s for s in signals if s.score < settings.BUY_THRESHOLD],
        key=lambda s: s.score,
    )

    render_page_hero(
        "Signals",
        "Algorithmic signal flow with premium card-driven scanning",
        "Signal ekranini feed odakli modern bir trading surface haline getirdim. Filtreler daha tutarli, kartlar daha zengin ve mobilde tek kolon akisa oturuyor.",
        badges=[
            f"Strong buy {len(strong)}",
            f"Buy {len(buy)}",
            f"Watchlist {len(watch)}",
        ],
        accent="secondary",
    )

    render_section_title("Signal filters", "Refine the live feed")
    with st.container():
        render_html_panel(
            "<div class='bb-note'>Use score, RSI and liquidity thresholds to narrow the feed.</div>"
        )
        f1, f2 = st.columns(2)
        with f1:
            st.session_state.min_score_filter = st.slider(
                get_message("ui.min_score"),
                -100,
                100,
                st.session_state.min_score_filter,
            )
            st.session_state.rsi_min_filter = st.slider(
                get_message("ui.rsi_min"), 0, 100, st.session_state.rsi_min_filter
            )
        with f2:
            st.session_state.rsi_max_filter = st.slider(
                get_message("ui.rsi_max"), 0, 100, st.session_state.rsi_max_filter
            )
            st.session_state.vol_ratio_filter = st.slider(
                "Min volume ratio",
                0.0,
                5.0,
                float(st.session_state.vol_ratio_filter),
                0.1,
            )

    strong_tab, buy_tab, watch_tab = st.tabs(
        [
            get_message("ui.strong_buy_tab"),
            get_message("ui.buy_tab"),
            f"Watch / Hold {len(watch)}",
        ]
    )
    with strong_tab:
        _render_signal_group("High conviction", strong, all_data)
    with buy_tab:
        _render_signal_group("Momentum continuation", buy, all_data)
    with watch_tab:
        _render_signal_group("Watchlist and defensive flow", watch, all_data)
