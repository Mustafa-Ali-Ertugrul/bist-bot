from __future__ import annotations

import html

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.locales import get_message
from bist_bot.ui.components.chart_widget import render_chart

_STRONG_BUY = int(settings.STRONG_BUY_THRESHOLD)
_WEAK_BUY = int(settings.WEAK_BUY_THRESHOLD)
_WEAK_SELL = int(settings.WEAK_SELL_THRESHOLD)


def _accent(score: float) -> tuple[str, str, str]:
    if score >= _STRONG_BUY:
        return ("bb-badge bb-badge-positive", "#4de2bf", "positive")
    if score >= _WEAK_BUY:
        return ("bb-badge", "#8ab4ff", "primary")
    if score > _WEAK_SELL:
        return ("bb-badge bb-badge-neutral", "#b0b0b0", "neutral")
    return ("bb-badge bb-badge-danger", "#ff8f8f", "danger")


def render_signal_card(signal, df_data=None, chart_factory=None) -> None:
    ticker = getattr(signal, "ticker", "")
    short_name = ticker.replace(".IS", "")
    badge_class, accent_color, panel_accent = _accent(float(getattr(signal, "score", 0)))
    confidence = str(getattr(signal, "confidence", "CACHE") or "CACHE").replace("confidence.", "")
    confidence_label = (
        get_message(f"confidence.{confidence.lower()}") if confidence != "CACHE" else "BELIRSIZ"
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
          <div class='bb-label'>Sinyal Akisi</div>
          <div style='font-size:30px;font-weight:900;letter-spacing:-.05em;margin-top:6px;color:var(--bb-text);'>{html.escape(short_name)}</div>
          <div class='bb-note'>{html.escape(ticker)}</div>
        </div>
        <span class='{badge_class}'>{html.escape(signal.signal_type.display)}</span>
      </div>
      <div style='display:flex;flex-wrap:wrap;gap:8px;'>
        <span class='bb-chip'>Guven {html.escape(confidence_label.title())}</span>
        <span class='bb-chip bb-chip-secondary'>Pozisyon boyutu {html.escape(str(signal.position_size if signal.position_size is not None else "-"))}</span>
      </div>
      <div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;'>
        <div class='bb-list-row'><div><div class='bb-label'>Fiyat</div><div class='bb-note-strong'>TL{signal.price:.2f}</div></div></div>
        <div class='bb-list-row'><div><div class='bb-label'>Skor</div><div class='bb-note-strong' style='color:{accent_color};'>{signal.score:+.0f}</div></div></div>
        <div class='bb-list-row'><div><div class='bb-label'>Stop loss</div><div class='bb-note-strong bb-text-danger'>TL{signal.stop_loss:.2f}</div></div></div>
        <div class='bb-list-row'><div><div class='bb-label'>Hedef</div><div class='bb-note-strong bb-text-positive'>TL{signal.target_price:.2f}</div></div></div>
      </div>
      <div>
        <div class='bb-section-title' style='margin:0 0 10px;'>Sinyal Nedenleri</div>
        <div class='bb-list'>{reasons_html or "<div class='bb-note'>Destekleyici neden henüz yok.</div>"}</div>
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
