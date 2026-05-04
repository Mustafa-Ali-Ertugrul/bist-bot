"""Streamlit entry point for the interactive operator dashboard."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from bist_bot.config.settings import settings
from bist_bot.state.session_state import init_session_state
from bist_bot.ui.components.app_shell import (
    PAGE_META,
    get_active_page,
    render_shell,
    set_active_page,
)
from bist_bot.ui.pages.analyze_page import render_analyze_page
from bist_bot.ui.pages.overview_page import render_overview_page
from bist_bot.ui.pages.scan_detail_page import render_scan_detail_page
from bist_bot.ui.pages.settings_page import render_settings_page
from bist_bot.ui.pages.signals_page import render_signals_page
from bist_bot.ui.runtime import api_request, prepare_streamlit_runtime
from bist_bot.ui.runtime_styles import inject_styles

st.set_page_config(
    page_title="BIST Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _response_message(response, default: str) -> str:
    """Extract a user-friendly error message from an HTTP response."""
    code = response.status_code
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        snippet = text[:120] if text else ""
        if code == 429:
            return "Cok fazla giris denemesi. Lutfen biraz bekleyip tekrar deneyin."
        if code == 401:
            return "Giris basarisiz. Email veya sifre hatali."
        if code >= 500:
            return f"API tarafinda hata olustu (HTTP {code}). Lutfen daha sonra tekrar deneyin."
        if snippet:
            return f"HTTP {code}: {snippet}"
        return default
    if isinstance(payload, dict):
        msg = payload.get("message", "")
        if msg:
            return str(msg)
    if code == 429:
        return "Cok fazla giris denemesi. Lutfen biraz bekleyip tekrar deneyin."
    if code == 401:
        return "Giris basarisiz. Email veya sifre hatali."
    if code >= 500:
        return f"API tarafinda hata olustu (HTTP {code}). Lutfen daha sonra tekrar deneyin."
    return default or f"HTTP {code}: bilinmeyen hata"


def _extract_token(response) -> str | None:
    """Safely extract access_token from a login/register response."""
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    token = payload.get("access_token")
    if not token or not isinstance(token, str) or not token.strip():
        return None
    return token.strip()


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
    st.query_params["page"] = "dashboard"
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
                token = _extract_token(response)
                if token:
                    _complete_auth(str(email), token)
                else:
                    st.error("Giris yaniti token icermiyor. Lutfen tekrar deneyin.")
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
                token = _extract_token(response)
                if token:
                    _complete_auth(str(register_email), token)
                else:
                    st.error("Kayit yaniti token icermiyor. Lutfen tekrar deneyin.")
            else:
                st.error(_response_message(response, "Kayit basarisiz."))
    return False


def _handle_shell_action(action: str | None) -> None:
    if not action:
        return
    if action == "logout":
        st.session_state.auth_token = None
        st.session_state.auth_email = ""
        st.session_state.is_authenticated = False
        st.session_state.app_bootstrapped = False
        st.session_state.just_logged_in = False
        set_active_page("dashboard")
        return
    if action.startswith("page:"):
        target = action.split(":", 1)[1].strip().lower()
        if target in PAGE_META:
            set_active_page(target)


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

    inject_styles()

    components.html(
        """
        <script>
        (function() {
            function forceSidebarOpen() {
                var sidebar = parent.document.querySelector('[data-testid="stSidebar"]');
                if (!sidebar) return;
                var expanded = sidebar.getAttribute('aria-expanded');
                if (expanded === 'false') {
                    var btn = parent.document.querySelector('[data-testid="stSidebarExpandButton"]');
                    if (btn) btn.click();
                }
            }
            forceSidebarOpen();
            setTimeout(forceSidebarOpen, 500);
            setTimeout(forceSidebarOpen, 1500);
        })();
        </script>
        """,
        height=0,
        width=0,
    )

    page = get_active_page()
    shell_action = render_shell(page, email=st.session_state.get("auth_email", ""))
    _handle_shell_action(shell_action)

    if page == "dashboard":
        render_overview_page()
    elif page == "scan":
        render_scan_detail_page()
    elif page == "signals":
        render_signals_page()
    elif page == "analysis":
        render_analyze_page()
    else:
        render_settings_page()


if __name__ == "__main__":
    main()
