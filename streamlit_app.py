import streamlit as st

from state.session_state import init_session_state
from ui.pages.backtest_page import render_backtest_page
from ui.pages.portfolio_page import render_portfolio_page
from ui.pages.settings_page import render_settings_page
from ui.pages.signals_page import render_signals_page
from ui.runtime import prepare_streamlit_runtime

st.set_page_config(
    page_title="BIST Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    init_session_state()
    prepare_streamlit_runtime()

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
