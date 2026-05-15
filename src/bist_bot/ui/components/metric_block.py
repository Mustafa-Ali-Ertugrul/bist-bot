from __future__ import annotations

import html

import streamlit as st


def render_metric_block(title: str, value: str, subtitle: str = "") -> None:
    safe_title = html.escape(str(title))
    safe_value = html.escape(str(value))
    safe_subtitle = html.escape(str(subtitle))
    st.markdown(
        (
            "<div style='background:rgba(28,32,38,0.92);border:1px solid rgba(255,255,255,0.06);"
            "border-radius:18px;padding:18px 20px;min-height:128px;'>"
            f"<div style='color:#8b90a0;text-transform:uppercase;letter-spacing:0.18em;font-size:10px;font-weight:800;'>{safe_title}</div>"
            f"<div style='font-size:34px;font-weight:900;letter-spacing:-0.04em;color:#dfe2eb;margin-top:8px;'>{safe_value}</div>"
            f"<div style='color:#99a2b2;font-size:12px;margin-top:8px;'>{safe_subtitle}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
