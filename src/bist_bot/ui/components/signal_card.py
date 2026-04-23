from __future__ import annotations

import html

import streamlit as st

from bist_bot.indicators import TechnicalIndicators
from bist_bot.ui.components.chart_widget import render_chart


def _accent(score: float) -> tuple[str, str, str]:
    if score >= 40:
        return ("bb-badge bb-badge-positive", "#4de2bf", "positive")
    if score >= 10:
        return ("bb-badge", "#8ab4ff", "primary")
    return ("bb-badge bb-badge-danger", "#ff8f8f", "danger")


def render_signal_card(signal, df_data=None, chart_factory=None) -> None:
    ticker = getattr(signal, "ticker", "")
    short_name = ticker.replace(".IS", "")
    badge_class, accent_color, panel_accent = _accent(
        float(getattr(signal, "score", 0))
    )
    confidence = str(getattr(signal, "confidence", "CACHE") or "CACHE").replace(
        "confidence.", ""
    )
    reasons = [html.escape(str(item)) for item in getattr(signal, "reasons", [])[:4]]
    reasons_html = "".join(
        f"<div class='bb-list-row'><div class='bb-list-row-subtitle'>{reason}</div></div>"
        for reason in reasons
    )

    content = f"""
    <div style='display:grid;gap:16px;'>
      <div style='display:flex;align-items:flex-start;justify-content:space-between;gap:14px;'>
        <div>
          <div class='bb-label'>Signal Feed</div>
          <div style='font-size:30px;font-weight:900;letter-spacing:-.05em;margin-top:6px;color:var(--bb-text);'>{html.escape(short_name)}</div>
          <div class='bb-note'>{html.escape(ticker)}</div>
        </div>
        <span class='{badge_class}'>{html.escape(signal.signal_type.display)}</span>
      </div>
      <div style='display:flex;flex-wrap:wrap;gap:8px;'>
        <span class='bb-chip'>Confidence {html.escape(confidence.upper())}</span>
        <span class='bb-chip bb-chip-secondary'>Position {html.escape(str(signal.position_size if signal.position_size is not None else "-"))}</span>
      </div>
      <div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;'>
        <div class='bb-list-row'><div><div class='bb-label'>Price</div><div class='bb-note-strong'>TL{signal.price:.2f}</div></div></div>
        <div class='bb-list-row'><div><div class='bb-label'>Score</div><div class='bb-note-strong' style='color:{accent_color};'>{signal.score:+.0f}</div></div></div>
        <div class='bb-list-row'><div><div class='bb-label'>Stop Loss</div><div class='bb-note-strong bb-text-danger'>TL{signal.stop_loss:.2f}</div></div></div>
        <div class='bb-list-row'><div><div class='bb-label'>Target</div><div class='bb-note-strong bb-text-positive'>TL{signal.target_price:.2f}</div></div></div>
      </div>
      <div>
        <div class='bb-section-title' style='margin:0 0 10px;'>Execution Reasons</div>
        <div class='bb-list'>{reasons_html or "<div class='bb-note'>No supporting reasons available.</div>"}</div>
      </div>
    </div>
    """

    if df_data is not None and chart_factory is not None:
        left, right = st.columns([1.1, 1], gap="large")
        with left:
            st.markdown(
                f"<section class='bb-panel bb-panel-{panel_accent}'>{content}</section>",
                unsafe_allow_html=True,
            )
        with right:
            try:
                df_chart = TechnicalIndicators().add_all(df_data.tail(60).copy())
                render_chart(
                    chart_factory(df_chart, ticker),
                    key=f"signal_chart_{ticker}",
                )
            except Exception:
                st.markdown(
                    f"<section class='bb-panel bb-panel-{panel_accent}'>{content}</section>",
                    unsafe_allow_html=True,
                )
    else:
        st.markdown(
            f"<section class='bb-panel bb-panel-{panel_accent}'>{content}</section>",
            unsafe_allow_html=True,
        )
