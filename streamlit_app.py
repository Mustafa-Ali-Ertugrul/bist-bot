"""Streamlit entry point for the interactive operator dashboard."""

import streamlit as st

from state.session_state import init_session_state
from ui.pages.backtest_page import render_backtest_page
from ui.pages.portfolio_page import render_portfolio_page
from ui.pages.settings_page import render_settings_page
from ui.pages.signals_page import render_signals_page
from ui.runtime import api_request, prepare_streamlit_runtime

st.set_page_config(
    page_title="BIST Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _login_form() -> bool:
    st.title("BIST Bot Giris")
    st.caption("Operator paneline erismek icin kimlik dogrulamasi yapin.")
    with st.form("login_form"):
        email = st.text_input("Email", value=st.session_state.get("auth_email", ""))
        password = st.text_input("Sifre", type="password")
        submitted = st.form_submit_button("Giris yap", use_container_width=True, type="primary")

    if submitted:
        try:
            response = api_request(
                "POST",
                "/api/auth/login",
                json={"email": email, "password": password},
            )
        except Exception as exc:
            st.error(f"API erisimi basarisiz: {exc}")
            return False
        if response.ok:
            payload = response.json()
            st.session_state.auth_token = payload["access_token"]
            st.session_state.auth_email = email
            st.session_state.is_authenticated = True
            st.rerun()
        else:
            st.error("Giris basarisiz. Email veya sifre hatali.")
    return False


def main() -> None:
    """Render the Streamlit UI pages and initialize shared runtime state."""
    init_session_state()
    if not st.session_state.get("is_authenticated"):
        _login_form()
        return

    prepare_streamlit_runtime()

    st.sidebar.caption(f"Oturum: {st.session_state.get('auth_email', '')}")
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state.auth_token = None
        st.session_state.auth_email = ""
        st.session_state.is_authenticated = False
        st.rerun()

    page = st.sidebar.radio(
        "Navigasyon",
        options=["Portfolio", "Signals", "Backtest", "Settings"],
        index=0,
    )

    if page == "Portfolio":
        render_portfolio_page()
    elif page == "Signals":
        render_signals_page()
    elif page == "Backtest":
        render_backtest_page()
    else:
        render_settings_page()


if __name__ == "__main__":
    main()
