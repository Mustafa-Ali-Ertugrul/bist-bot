from __future__ import annotations

import streamlit as st

from bist_bot.indicators import TechnicalIndicators
from bist_bot.ui.components.chart_widget import render_chart


def render_signal_card(signal, df_data=None, chart_factory=None) -> None:
    name = getattr(signal, "ticker", "").replace(".IS", "")
    full_name = getattr(signal, "ticker", "") if not hasattr(signal, "ticker") else signal.ticker
    if signal.score >= 10:
        card_class = "rgba(72,221,188,0.04)"
        chip_bg = "rgba(72,221,188,0.12)"
        chip_color = "#48ddbc"
    elif signal.score >= 0:
        card_class = "rgba(173,198,255,0.06)"
        chip_bg = "rgba(173,198,255,0.12)"
        chip_color = "#adc6ff"
    else:
        card_class = "rgba(255,121,108,0.04)"
        chip_bg = "rgba(255,121,108,0.12)"
        chip_color = "#ff796c"

    left_html = f"""
    <div style='border:1px solid rgba(255,255,255,0.06);background:{card_class};border-radius:20px;padding:20px;'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:flex-start;'>
        <div>
          <div style='font-size:26px;font-weight:900;letter-spacing:-0.03em;color:#dfe2eb;'>{name}</div>
          <div style='font-size:12px;color:#8b90a0;margin-top:2px;'>{full_name}</div>
        </div>
        <span style='display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;background:{chip_bg};color:{chip_color};'>{signal.signal_type.display}</span>
      </div>
      <div style='margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:8px;'>
        <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'><div style='font-size:10px;color:#8b90a0;font-weight:700;text-transform:uppercase;'>Fiyat</div><div style='font-size:18px;font-weight:800;color:#dfe2eb;margin-top:2px;'>TL{signal.price:.2f}</div></div>
        <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'><div style='font-size:10px;color:#8b90a0;font-weight:700;text-transform:uppercase;'>Skor</div><div style='font-size:18px;font-weight:800;color:{chip_color};margin-top:2px;'>{signal.score:+.0f}</div></div>
        <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'><div style='font-size:10px;color:#8b90a0;font-weight:700;text-transform:uppercase;'>Stop</div><div style='font-size:18px;font-weight:800;color:#ff796c;margin-top:2px;'>TL{signal.stop_loss:.2f}</div></div>
        <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'><div style='font-size:10px;color:#8b90a0;font-weight:700;text-transform:uppercase;'>Hedef</div><div style='font-size:18px;font-weight:800;color:#48ddbc;margin-top:2px;'>TL{signal.target_price:.2f}</div></div>
        <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'><div style='font-size:10px;color:#8b90a0;font-weight:700;text-transform:uppercase;'>Lot</div><div style='font-size:18px;font-weight:800;color:#dfe2eb;margin-top:2px;'>{signal.position_size if signal.position_size is not None else "-"}</div></div>
      </div>
      <div style='margin-top:12px;color:#99a2b2;font-size:12px;line-height:1.6;'>{"<br>".join(signal.reasons[:5])}</div>
    </div>
    """

    if df_data is not None and chart_factory is not None:
        col_left, col_right = st.columns([1.4, 1])
        with col_left:
            st.markdown(left_html, unsafe_allow_html=True)
        with col_right:
            try:
                df_chart = TechnicalIndicators().add_all(df_data.tail(60).copy())
                render_chart(
                    chart_factory(df_chart, signal.ticker), key=f"signal_chart_{signal.ticker}"
                )
            except Exception:
                st.markdown(left_html, unsafe_allow_html=True)
    else:
        st.markdown(left_html, unsafe_allow_html=True)
