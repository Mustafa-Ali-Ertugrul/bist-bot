"""Streamlit entry point for the interactive operator dashboard."""

from __future__ import annotations

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.state.session_state import init_session_state
from bist_bot.ui.components.app_shell import (
    get_active_page,
    render_bottom_nav,
    render_shell,
    set_active_page,
)
from bist_bot.ui.pages.analyze_page import render_analyze_page
from bist_bot.ui.pages.overview_page import render_overview_page
from bist_bot.ui.pages.settings_page import render_settings_page
from bist_bot.ui.pages.signals_page import render_signals_page
from bist_bot.ui.runtime import api_request, prepare_streamlit_runtime
from bist_bot.ui.runtime_styles import inject_styles

st.set_page_config(
    page_title="BIST Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _response_message(response, default: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or default
    if isinstance(payload, dict):
        return str(payload.get("message", default))
    return default


def _handle_query_actions() -> None:
    action = str(st.query_params.get("action", "")).lower().strip()
    if action != "logout":
        return
    st.session_state.auth_token = None
    st.session_state.auth_email = ""
    st.session_state.is_authenticated = False
    st.session_state.app_bootstrapped = False
    st.session_state.just_logged_in = False
    try:
        del st.query_params["action"]
    except KeyError:
        pass
    st.rerun()


def _complete_auth(email: str, token: str) -> None:
    st.session_state.auth_token = token
    st.session_state.auth_email = email
    st.session_state.is_authenticated = True
    st.session_state.app_bootstrapped = False
    st.session_state.just_logged_in = True
    set_active_page("dashboard")
    st.rerun()


def _login_form() -> bool:
    st.markdown(
        """
        <section class="bb-hero bb-hero-secondary">
          <div class="bb-kicker">BIST Bot Access</div>
          <div class="bb-title">Operator authentication for the premium trading console</div>
          <div class="bb-subtitle">Neon dark fintech arayuzu artik giris ekraninda da devam ediyor. Hesabinizla oturum acip dashboard, signals, analysis ve settings yuzeylerine erisebilirsiniz.</div>
          <div class="bb-chip-row">
            <span class="bb-chip">Secure JWT Access</span>
            <span class="bb-chip bb-chip-secondary">Mobile-first UI</span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    auth_tabs = ["Giris"]
    if settings.ALLOW_PUBLIC_REGISTRATION:
        auth_tabs.append("Kaydol")
    tabs = st.tabs(auth_tabs)

    with tabs[0]:
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
                _complete_auth(str(email), payload["access_token"])
            else:
                st.error(_response_message(response, "Giris basarisiz. Email veya sifre hatali."))

    if not settings.ALLOW_PUBLIC_REGISTRATION:
        st.info("Yeni hesap kaydi kapali. Lutfen tanimli operator hesabi ile giris yapin.")
        return False

    with tabs[1]:
        with st.form("register_form"):
            register_email = st.text_input("Email", key="register_email")
            register_password = st.text_input("Sifre", type="password", key="register_password")
            register_password_confirm = st.text_input(
                "Sifre tekrar", type="password", key="register_password_confirm"
            )
            register_submitted = st.form_submit_button(
                "Kaydol", use_container_width=True, type="primary"
            )

        if register_submitted:
            if register_password != register_password_confirm:
                st.error("Sifreler eslesmiyor.")
                return False
            try:
                response = api_request(
                    "POST",
                    "/api/auth/register",
                    json={"email": register_email, "password": register_password},
                )
            except Exception as exc:
                st.error(f"API erisimi basarisiz: {exc}")
                return False
            if response.ok:
                payload = response.json()
                _complete_auth(str(register_email), payload["access_token"])
            else:
                st.error(_response_message(response, "Kayit basarisiz."))
    return False


def _handle_shell_action(action: str | None) -> None:
    if action == "logout":
        st.session_state.auth_token = None
        st.session_state.auth_email = ""
        st.session_state.is_authenticated = False
        st.session_state.app_bootstrapped = False
        st.session_state.just_logged_in = False
        set_active_page("dashboard")
    if action and action != "logout":
        set_active_page(action)


def _bootstrap_authenticated_app() -> None:
    if not st.session_state.get("just_logged_in"):
        return
    with st.spinner("Uygulama yukleniyor, veriler hazirlaniyor..."):
        prepare_streamlit_runtime()
    st.session_state.just_logged_in = False
    st.session_state.app_bootstrapped = True
    st.rerun()


def main() -> None:
    """Render the Streamlit UI pages and initialize shared runtime state."""
    init_session_state()
    _handle_query_actions()
    if not st.session_state.get("is_authenticated"):
        inject_styles()
        _login_form()
        return

    _bootstrap_authenticated_app()
    prepare_streamlit_runtime()
    st.session_state.app_bootstrapped = True

    page = get_active_page()
    shell_action = render_shell(page, email=st.session_state.get("auth_email", ""))
    _handle_shell_action(shell_action)

    if page == "dashboard":
        render_overview_page()
    elif page == "signals":
        render_signals_page()
    elif page == "analysis":
        render_analyze_page()
    else:
        render_settings_page()

    nav_action = render_bottom_nav(page)
    _handle_shell_action(nav_action)


if __name__ == "__main__":
    main()
