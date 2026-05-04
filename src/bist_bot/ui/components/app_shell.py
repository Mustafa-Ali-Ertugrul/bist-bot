from __future__ import annotations

import html
from typing import Literal

import streamlit as st

PAGE_META = {
    "dashboard": {"label": "Dashboard", "icon": "dashboard"},
    "scan": {"label": "Scan Detail", "icon": "monitoring"},
    "signals": {"label": "Signals", "icon": "query_stats"},
    "analysis": {"label": "Analysis", "icon": "analytics"},
    "settings": {"label": "Settings", "icon": "settings"},
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
    st.query_params["page"] = page
    return page


def _nav_action(page: str) -> str:
    return f"page:{page}"


def render_sidebar_nav(active_page: str) -> str | None:
    page_keys = list(PAGE_META)
    active_index = page_keys.index(active_page) if active_page in PAGE_META else 0
    active_label = PAGE_META[page_keys[active_index]]["label"]
    if st.session_state.get("_sidebar_active_page") != active_page:
        st.session_state["sidebar_page_radio"] = active_label
        st.session_state["_sidebar_active_page"] = active_page

    with st.sidebar:
        st.markdown(
            ("<div class='bb-sidebar-shell'><div class='bb-sidebar-kicker'>Navigation</div></div>"),
            unsafe_allow_html=True,
        )
        selected_label = st.radio(
            "Navigation",
            [PAGE_META[page]["label"] for page in page_keys],
            index=active_index,
            key="sidebar_page_radio",
            label_visibility="collapsed",
        )

    selected_page = page_keys[
        [PAGE_META[page]["label"] for page in page_keys].index(selected_label)
    ]
    if selected_page != active_page:
        return _nav_action(selected_page)
    return None


def render_shell(active_page: str, email: str = "") -> str | None:
    active_label = PAGE_META[active_page]["label"]
    email_label = html.escape(email or "Guest Session")

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
            "</div>"
            "</header>"
        ),
        unsafe_allow_html=True,
    )

    action: str | None = None
    st.markdown("<div class='bb-logout-wrap'>", unsafe_allow_html=True)
    button_type: Literal["primary", "secondary", "tertiary"] = "secondary"
    if st.button("Logout", key="top_logout", use_container_width=True, type=button_type):
        action = "logout"
    st.markdown("</div>", unsafe_allow_html=True)
    nav_action = render_sidebar_nav(active_page)
    if nav_action:
        action = nav_action
    return action


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
