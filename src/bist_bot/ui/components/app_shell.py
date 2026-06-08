from __future__ import annotations

import html

import streamlit as st

PAGE_META = {
    "dashboard": {"label": "İşlem Paneli", "icon": "dashboard"},
    "scan": {"label": "Tarama Detayı", "icon": "monitoring"},
    "signals": {"label": "Sinyaller", "icon": "query_stats"},
    "whale": {"label": "Balina Radar", "icon": "radar"},
    "analysis": {"label": "Analiz", "icon": "analytics"},
    "settings": {"label": "Ayarlar", "icon": "settings"},
}


def set_active_page(page: str) -> None:
    target = page if page in PAGE_META else "dashboard"
    st.query_params["page"] = target
    st.rerun()


def mask_secret(value: str | None, prefix: int = 4, suffix: int = 3) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Not configured"
    if len(raw) <= prefix + suffix:
        return "*" * len(raw)
    return f"{raw[:prefix]}{'*' * max(4, len(raw) - prefix - suffix)}{raw[-suffix:]}"


def get_active_page(default: str = "dashboard") -> str:
    page = str(st.query_params.get("page", default)).lower().strip()
    if page not in PAGE_META:
        page = default
    return page


def render_shell(active_page: str, email: str = "") -> None:
    active_label = PAGE_META[active_page]["label"]
    email_label = html.escape(email or "Misafir Oturumu")

    st.markdown(
        (
            "<header class='bb-topbar'>"
            "<div class='bb-topbar-brand'>"
            "<div class='bb-brand-mark'>BB</div>"
            "<div>"
            "<div class='bb-topbar-kicker'>Live Terminal</div>"
            "<div class='bb-topbar-title'>Bist-Bot</div>"
            "</div>"
            "</div>"
            "<div class='bb-topbar-actions'>"
            f"<span class='bb-badge bb-badge-positive'>{html.escape(active_label)}</span>"
            f"<span class='bb-session-pill'>{email_label}</span>"
            "<a class='bb-logout-link' href='?action=logout'>Çıkış</a>"
            "</div>"
            "</header>"
        ),
        unsafe_allow_html=True,
    )


def render_page_hero(
    eyebrow: str,
    title: str,
    subtitle: str,
    badges: list[str] | None = None,
    accent: str = "primary",
) -> None:
    badge_html = "".join(
        f"<span class='bb-chip{' bb-chip-secondary' if accent == 'secondary' else ''}'>{html.escape(item)}</span>"
        for item in (badges or [])
    )
    st.markdown(
        (
            f"<section class='bb-hero bb-hero-{accent}'>"
            f"<div class='bb-kicker'>{html.escape(eyebrow)}</div>"
            f"<div class='bb-title'>{html.escape(title)}</div>"
            f"<div class='bb-subtitle'>{html.escape(subtitle)}</div>"
            f"<div class='bb-chip-row'>{badge_html}</div>"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_section_title(title: str, caption: str = "") -> None:
    caption_html = (
        f"<div class='bb-section-caption'>{html.escape(caption)}</div>" if caption else ""
    )
    st.markdown(
        (
            "<div class='bb-section-head'>"
            f"<div class='bb-section-title'>{html.escape(title)}</div>"
            f"{caption_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_html_panel(content: str, accent: str = "") -> None:
    accent_class = f" bb-panel-{accent}" if accent else ""
    st.markdown(
        f"<section class='bb-panel{accent_class}'>{content}</section>",
        unsafe_allow_html=True,
    )
