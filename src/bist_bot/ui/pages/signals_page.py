from __future__ import annotations

import streamlit as st

from bist_bot.config.settings import settings
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
    render_section_title(title, f"{len(items)} visible signals")
    if not items:
        st.info(f"{title} icin uygun sinyal yok.")
        return
    for signal in items:
        render_signal_card(signal, all_data.get(signal.ticker), plot_candlestick)


def render_signals_page() -> None:
    all_data = st.session_state.get("all_data", {})
    base_signals = st.session_state.get("signals", [])
    signals = filter_signals(base_signals, all_data)

    strong = sorted([s for s in signals if s.score >= settings.STRONG_BUY_THRESHOLD], key=lambda s: s.score, reverse=True)
    buy = sorted([s for s in signals if settings.BUY_THRESHOLD <= s.score < settings.STRONG_BUY_THRESHOLD], key=lambda s: s.score, reverse=True)
    watch = sorted([s for s in signals if s.score < settings.BUY_THRESHOLD], key=lambda s: s.score)

    scanned_count = len(all_data)
    generated_count = len(base_signals)
    visible_count = len(signals)
    filtered_out_count = max(generated_count - visible_count, 0)

    render_page_hero(
        "Signals",
        "Algorithmic signal flow with explicit scan, generation and visibility counts",
        f"{scanned_count} asset tarandi, {generated_count} sinyal uretildi ve "
        f"{visible_count} tanesi aktif UI filtrelerinden sonra gorunur kaldi.",
        badges=[
            f"Scanned {scanned_count}",
            f"Visible {visible_count}",
            f"Strong buy {len(strong)}",
            f"Buy {len(buy)}",
            f"Watch / Sell {len(watch)}",
        ],
        accent="secondary",
    )

    render_section_title("Signal filters", "Refine the live feed")
    with st.container():
        render_html_panel(
            "<div class='bb-note'>"
            f"Backend {generated_count} sinyal urettigi halde sadece {visible_count} tanesi mevcut UI filtrelerinden geciyor. "
            f"Filtre disinda kalan sinyal sayisi: {filtered_out_count}."
            "</div>"
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
            "Watch / Sell",
        ]
    )
    with strong_tab:
        _render_signal_group("High conviction", strong, all_data)
    with buy_tab:
        _render_signal_group("Momentum continuation", buy, all_data)
    with watch_tab:
        _render_signal_group("Watchlist and defensive flow", watch, all_data)
