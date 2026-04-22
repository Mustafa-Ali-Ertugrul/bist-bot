"""Visual style helpers for the Streamlit runtime."""

from __future__ import annotations

import streamlit as st


def inject_styles() -> None:
    """Inject shared Streamlit layout styles."""
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] {background:linear-gradient(180deg,#121823,#0d1118);border-right:1px solid rgba(255,255,255,.06)}
            [data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu {display:none !important;}
            .block-container {max-width:1240px;padding-top:1.2rem;padding-bottom:2rem;}
            .stApp {background:radial-gradient(circle at top right, rgba(72,221,188,0.08), transparent 24%),linear-gradient(180deg,#0b1016 0%,#10141a 100%);}
        </style>
        """,
        unsafe_allow_html=True,
    )
