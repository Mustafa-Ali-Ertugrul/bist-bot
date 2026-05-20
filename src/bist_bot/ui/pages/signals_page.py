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


def _render_filter_status_html(
    *, generated_count: int, visible_count: int, filtered_out_count: int
) -> str:
    if filtered_out_count <= 0:
        return (
            "<div class='bb-note'>"
            f"Tüm sinyaller görünür: üretilen {generated_count} sinyalin {visible_count} tanesi "
            "mevcut filtrelerden geçti."
            "</div>"
        )
    return (
        "<div class='bb-note'>"
        f"Üretilen {generated_count} sinyalin {visible_count} tanesi görünür. "
        f"Skor, RSI veya hacim filtresi nedeniyle {filtered_out_count} sinyal gizlendi."
        "</div>"
    )


def _render_signal_group(title: str, items, all_data) -> None:
    render_section_title(title, f"{len(items)} görünür sinyal")
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
        get_message("ui.signals_title"),
        "Premium kart tabanlı tarama ile algoritmik sinyal akışı",
        f"Arka plan {scanned_count} varlığı taradı ve {generated_count} sinyal üretti. "
        f"Arayüz filtrelerinden sonra: {visible_count} görünür, {filtered_out_count} filtrelendi.",
        badges=[
            f"Taranan {scanned_count}",
            f"Görünür {visible_count}",
            f"Al {buy_count}",
            f"Tut {len(hold)}",
            f"Sat {sell_count}",
        ],
        accent="secondary",
    )

    if filtered_out_count > 0:
        render_html_panel(
            f"<div class='bb-note'>"
            f"Arka plan, taranan {scanned_count} varlıktan {generated_count} sinyal üretti. "
            f"Arayüz filtreleri (skor, RSI, hacim) bunlardan {filtered_out_count} tanesini gizledi. "
            f"Daha fazlasını görmek için aşağıdaki filtreleri ayarlayın."
            f"</div>"
        )

    render_section_title("Sinyal filtreleri", "Canlı akışı filtreleyin")
    with st.container():
        render_html_panel(
            _render_filter_status_html(
                generated_count=generated_count,
                visible_count=visible_count,
                filtered_out_count=filtered_out_count,
            )
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
                "Min hacim oranı",
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
        _render_signal_group("Yüksek Güven", strong_buy, all_data)
        _render_signal_group("Momentum Devamı", buy, all_data)
    with neutral_tab:
        _render_signal_group("Tut / İzle", hold, all_data)
    with sell_tab:
        _render_signal_group("Zayıf Sat", weak_sell, all_data)
        _render_signal_group("Sat", sell, all_data)
        _render_signal_group("Güçlü Sat", strong_sell, all_data)
