from __future__ import annotations

import html

import streamlit as st


def render_metric_block(
    title: str,
    value: str,
    subtitle: str = "",
    accent: str = "primary",
    bar_pct: float | None = None,
) -> None:
    safe_title = html.escape(str(title))
    safe_value = html.escape(str(value))
    safe_subtitle = html.escape(str(subtitle))
    accent_class = {
        "positive": " bb-metric-positive",
        "danger": " bb-metric-danger",
    }.get(accent, "")
    bar_html = ""
    if bar_pct is not None:
        try:
            pct = max(0.0, min(100.0, float(bar_pct)))
        except (TypeError, ValueError):
            pct = 0.0
        bar_html = (
            "<div class='bb-meter'>"
            f"<div class='bb-meter-fill' style='width:{pct:.0f}%'></div>"
            "</div>"
        )
    st.markdown(
        (
            f"<section class='bb-metric-card{accent_class}'>"
            f"<div class='bb-label'>{safe_title}</div>"
            f"<div class='bb-metric-card-value'>{safe_value}</div>"
            f"{bar_html}"
            f"<div class='bb-metric-card-subtitle'>{safe_subtitle}</div>"
            "</section>"
        ),
        unsafe_allow_html=True,
    )
