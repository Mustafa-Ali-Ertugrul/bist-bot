"""Visual style helpers for the Streamlit runtime."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import streamlit as st

_STYLE_TEMPLATE_PATH = Path(__file__).with_name("runtime_styles.css")


@lru_cache(maxsize=1)
def _load_style_template() -> str:
    return _STYLE_TEMPLATE_PATH.read_text(encoding="utf-8")


def inject_styles(sidebar_collapsed: bool = False) -> None:
    """Inject shared Streamlit layout styles."""
    tl = "0" if sidebar_collapsed else "236px"
    bc_mw = "1520px" if sidebar_collapsed else "calc(100vw - 236px)"
    bc_ml = "auto" if sidebar_collapsed else "236px"
    sw = "0" if sidebar_collapsed else "236px"
    sd = "none" if sidebar_collapsed else "block"
    mobile_tl = "0" if sidebar_collapsed else "208px"
    mobile_bc_mw = "100vw" if sidebar_collapsed else "calc(100vw - 208px)"
    mobile_bc_ml = "0" if sidebar_collapsed else "208px"
    mobile_sw = "0" if sidebar_collapsed else "208px"
    toggle_left = "20px" if sidebar_collapsed else f"calc({tl} + 24px)"
    mobile_toggle_left = "20px" if sidebar_collapsed else f"calc({mobile_tl} + 24px)"
    css = _load_style_template().format(
        bc_ml=bc_ml,
        bc_mw=bc_mw,
        mobile_bc_ml=mobile_bc_ml,
        mobile_bc_mw=mobile_bc_mw,
        mobile_sw=mobile_sw,
        mobile_tl=mobile_tl,
        mobile_toggle_left=mobile_toggle_left,
        sd=sd,
        sw=sw,
        tl=tl,
        toggle_left=toggle_left,
    )
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
