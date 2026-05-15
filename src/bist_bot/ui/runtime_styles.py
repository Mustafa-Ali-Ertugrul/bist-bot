"""Visual style helpers for the Streamlit runtime."""

from __future__ import annotations

import streamlit as st


def inject_styles() -> None:
    """Inject a restrained Streamlit layout without the fixed terminal shell."""
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] {
                background: linear-gradient(180deg, #121823, #0d1118);
                border-right: 1px solid rgba(255, 255, 255, .06);
            }
            [data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu {
                display: none !important;
            }
            .block-container {
                max-width: 1240px;
                padding-top: 1.2rem;
                padding-bottom: 2rem;
            }
            .stApp {
                background:
                    radial-gradient(circle at top right, rgba(72, 221, 188, .08), transparent 24%),
                    linear-gradient(180deg, #0b1016 0%, #10141a 100%);
            }
            .bb-topbar,
            .bb-logout-wrap {
                display: none !important;
            }
            .bb-hero,
            .bb-panel,
            .bb-list-row,
            .bb-stat-card {
                border: 1px solid rgba(255, 255, 255, .08);
                border-radius: 12px;
                background: rgba(255, 255, 255, .03);
                padding: 1rem;
                margin-bottom: .75rem;
            }
            .bb-title,
            .bb-section-title,
            .bb-list-row-title,
            .bb-note-strong {
                font-weight: 700;
            }
            .bb-kicker,
            .bb-section-caption,
            .bb-label,
            .bb-list-row-subtitle,
            .bb-note {
                opacity: .78;
                font-size: .88rem;
            }
            .bb-chip,
            .bb-badge {
                display: inline-block;
                border: 1px solid rgba(255, 255, 255, .12);
                border-radius: 999px;
                padding: .25rem .55rem;
                margin: .15rem .25rem .15rem 0;
                font-size: .78rem;
            }
            .bb-text-positive { color: #4de2bf; }
            .bb-text-danger { color: #ff8f8f; }
            .bb-table {
                width: 100%;
                border-collapse: collapse;
            }
            .bb-table th,
            .bb-table td {
                border-bottom: 1px solid rgba(255, 255, 255, .08);
                padding: .5rem;
                text-align: left;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
