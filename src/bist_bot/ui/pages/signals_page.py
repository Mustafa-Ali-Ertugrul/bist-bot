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

_STRONG_BUY = int(settings.STRONG_BUY_THRESHOLD)
_BUY = int(settings.BUY_THRESHOLD)
_WEAK_BUY = int(settings.WEAK_BUY_THRESHOLD)
_WEAK_SELL = int(settings.WEAK_SELL_THRESHOLD)
_SELL = int(settings.SELL_THRESHOLD)
_STRONG_SELL = int(settings.STRONG_SELL_THRESHOLD)


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

    scanned_count = len(all_data)
    generated_count = len(base_signals)
    visible_count = len(signals)
    filtered_out_count = generated_count - visible_count

    strong_buy = sorted(
        [s for s in signals if s.score >= _STRONG_BUY], key=lambda s: s.score, reverse=True
    )
    buy = sorted(
        [s for s in signals if _BUY <= s.score < _STRONG_BUY], key=lambda s: s.score, reverse=True
    )
    hold = sorted(
        [s for s in signals if _WEAK_SELL < s.score < _WEAK_BUY], key=lambda s: abs(s.score)
    )
    weak_sell = sorted([s for s in signals if _SELL < s.score <= _WEAK_SELL], key=lambda s: s.score)
    sell = sorted([s for s in signals if _STRONG_SELL < s.score <= _SELL], key=lambda s: s.score)
    strong_sell = sorted([s for s in signals if s.score <= _STRONG_SELL], key=lambda s: s.score)

    buy_count = len(strong_buy) + len(buy)
    sell_count = len(weak_sell) + len(sell) + len(strong_sell)

    render_page_hero(
        "Signals",
        "Algorithmic signal flow with premium card-driven scanning",
        f"Backend scanned {scanned_count} assets and generated {generated_count} signals. "
        f"After UI filters: {visible_count} visible, {filtered_out_count} filtered out.",
        badges=[
            f"Scanned {scanned_count}",
            f"Visible {visible_count}",
            f"Buy {buy_count}",
            f"Hold {len(hold)}",
            f"Sell {sell_count}",
        ],
        accent="secondary",
    )

    if filtered_out_count > 0:
        render_html_panel(
            f"<div class='bb-note'>"
            f"Backend produced {generated_count} signals from {scanned_count} scanned assets. "
            f"UI filters (score, RSI, volume) hid {filtered_out_count} of them. "
            f"Adjust filters below to see more."
            f"</div>"
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

    buy_tab, neutral_tab, sell_tab = st.tabs(
        [
            get_message("ui.buy_side_tab"),
            get_message("ui.neutral_tab"),
            get_message("ui.sell_side_tab"),
        ]
    )
    with buy_tab:
        _render_signal_group("High conviction", strong_buy, all_data)
        _render_signal_group("Momentum continuation", buy, all_data)
    with neutral_tab:
        _render_signal_group("Hold / Watch", hold, all_data)
    with sell_tab:
        _render_signal_group("Weak sell", weak_sell, all_data)
        _render_signal_group("Sell", sell, all_data)
        _render_signal_group("Strong sell", strong_sell, all_data)
