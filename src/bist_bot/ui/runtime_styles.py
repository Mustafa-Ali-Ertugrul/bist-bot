"""Visual style helpers for the Streamlit runtime."""

from __future__ import annotations

import time
import urllib.request
from importlib.metadata import PackageNotFoundError, version

import streamlit as st

_FOOTER_STATUS_TTL_SECONDS = 60.0
_FOOTER_VERSION_FALLBACK = "0.1.0"


def get_footer_version() -> str:
    cached = st.session_state.get("bb_footer_version")
    if isinstance(cached, str) and cached:
        return cached
    detected = ""
    try:
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        detected = str(
            tomllib.loads(pyproject.read_text(encoding="utf-8"))
            .get("project", {})
            .get("version", "")
        )
    except Exception:
        detected = ""
    if not detected:
        try:
            detected = version("bist-bot")
        except PackageNotFoundError:
            detected = ""
    if not detected or detected == "0.0.0":
        detected = _FOOTER_VERSION_FALLBACK
    st.session_state["bb_footer_version"] = detected
    return detected


def get_footer_api_status() -> bool:
    """Return cached API liveness (False when unreachable)."""
    now = time.monotonic()
    cached = st.session_state.get("bb_footer_api")
    if isinstance(cached, dict) and now - float(cached.get("at", 0.0)) < _FOOTER_STATUS_TTL_SECONDS:
        return bool(cached.get("online"))
    online = False
    try:
        from bist_bot.config.settings import settings

        base = str(getattr(settings, "API_BASE_URL", "") or "").rstrip("/")
        if base and base.startswith(("http://", "https://")):
            req = urllib.request.Request(f"{base}/livez")
            with urllib.request.urlopen(req, timeout=2) as response:  # nosec B310
                online = 200 <= int(getattr(response, "status", 0)) < 300
    except Exception:
        online = False
    st.session_state["bb_footer_api"] = {"at": now, "online": online}
    return online


def footer_meta_html() -> str:
    """Shared footer meta row (version, API status, disclaimer, GitHub)."""
    online = get_footer_api_status()
    dot = "#4de2bf" if online else "#ff8f8f"
    label = "API çevrimiçi" if online else "API erişilemiyor"
    return (
        '<div class="bb-footer-meta">'
        f"<span class='bb-footer-brand'>BIST Bot • v{get_footer_version()}</span>"
        f"<span class='bb-footer-dot' style='background:{dot}'></span>"
        f"<span class='bb-footer-status'>{label}</span>"
        "<span class='bb-footer-sep'>•</span>"
        "<span class='bb-footer-note'>Veriler bilgilendirme amaçlıdır, yatırım tavsiyesi değildir.</span>"
        "<span class='bb-footer-sep'>•</span>"
        "<a class='bb-footer-link' href='https://github.com/Mustafa-Ali-Ertugrul/bist-bot' "
        "target='_blank' rel='noopener'>GitHub</a>"
        "</div>"
    )


def render_footer() -> None:
    """Render the shared bottom footer (meta row only, e.g. login page)."""
    with st.container(key="footer_navigation"):
        st.markdown(footer_meta_html(), unsafe_allow_html=True)


def inject_styles() -> None:
    """Inject shared Streamlit layout styles."""
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;700&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,500,0,0&display=swap');
            :root {
                --bb-bg:#0a0f16;
                --bb-bg-soft:#101722;
                --bb-surface:#121a24;
                --bb-surface-2:#182230;
                --bb-surface-3:#1d2938;
                --bb-surface-4:#223245;
                --bb-outline:rgba(173,198,255,.12);
                --bb-outline-strong:rgba(173,198,255,.22);
                --bb-text:#eef3ff;
                --bb-muted:#b0bfd8;
                --bb-faint:#73839d;
                --bb-primary:#8ab4ff;
                --bb-primary-strong:#4b8eff;
                --bb-secondary:#4de2bf;
                --bb-danger:#ff8f8f;
                --bb-warning:#ffd38a;
                --bb-radius:26px;
                --bb-radius-sm:18px;
                --bb-shadow:0 30px 80px rgba(0, 0, 0, .36);
            }
            [data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu {
                display:none !important;
            }
            html, body, [class*="css"] {
                font-family:'Inter',sans-serif;
            }
            .stApp {
                background:
                    radial-gradient(circle at 0% 0%, rgba(77,226,191,.14), transparent 28%),
                    radial-gradient(circle at 100% 0%, rgba(138,180,255,.18), transparent 34%),
                    radial-gradient(circle at 50% 100%, rgba(50,95,190,.12), transparent 28%),
                    linear-gradient(180deg, #091019 0%, #0a0f16 100%);
                color:var(--bb-text);
            }
            .block-container {
                max-width:1520px;
                padding:8.5rem 2.5rem 3rem 2rem;
            }
            .bb-live-pill {
                display:inline-flex;
                align-items:center;
                gap:6px;
                margin-left:10px;
                padding:5px 10px;
                border-radius:999px;
                background:rgba(77,226,191,.10);
                border:1px solid rgba(77,226,191,.22);
                color:var(--bb-secondary);
                font-family:'Space Grotesk',sans-serif;
                font-size:9px;
                font-weight:700;
                letter-spacing:.14em;
            }
            .bb-live-pill i {
                width:7px;
                height:7px;
                border-radius:999px;
                background:var(--bb-secondary);
                box-shadow:0 0 8px rgba(77,226,191,.8);
            }
            .bb-topnav {
                display:flex;
                align-items:center;
                gap:4px;
            }
            .bb-nav-link {
                padding:9px 14px;
                border-radius:12px;
                color:var(--bb-muted) !important;
                font-family:'Space Grotesk',sans-serif;
                font-size:11px;
                font-weight:700;
                letter-spacing:.08em;
                text-transform:uppercase;
            }
            .bb-nav-link:hover {
                color:var(--bb-text) !important;
                background:rgba(255,255,255,.05);
            }
            .bb-nav-link.active {
                color:var(--bb-secondary) !important;
                background:rgba(77,226,191,.10);
            }
            .bb-tape {
                position:fixed;
                top:68px;
                left:0;
                right:0;
                z-index:998;
                display:flex;
                align-items:center;
                gap:10px;
                padding:7px 20px;
                background:rgba(9,15,25,.82);
                backdrop-filter:blur(22px);
                border-bottom:1px solid rgba(255,255,255,.05);
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.1em;
                color:var(--bb-muted);
                overflow:hidden;
                white-space:nowrap;
            }
            .bb-tape-item b {
                color:var(--bb-text);
            }
            .bb-tape-item i {
                font-style:normal;
            }
            .bb-tape-item i.up {
                color:var(--bb-secondary);
            }
            .bb-tape-item i.down {
                color:var(--bb-danger);
            }
            .bb-tape-sep {
                opacity:.4;
            }
            [data-testid="stVerticalBlock"] > [style*="flex-direction: column"] {
                gap:1rem;
            }
            .stApp a {
                color:inherit;
                text-decoration:none;
            }
            .bb-topbar {
                position:fixed;
                top:0;
                left:0;
                right:0;
                z-index:999;
                height:68px;
                display:flex;
                align-items:center;
                justify-content:space-between;
                padding:0 20px;
                background:rgba(9, 15, 25, .78);
                backdrop-filter:blur(22px);
                border-bottom:1px solid rgba(255,255,255,.05);
            }
            .bb-topbar-brand, .bb-topbar-actions {
                display:flex;
                align-items:center;
                gap:12px;
            }
            #bb-sidebar-toggle-client {
                position:fixed;
                top:18px;
                left:188px;
                z-index:1002;
                width:32px;
                height:32px;
                border-radius:10px;
                display:inline-flex;
                align-items:center;
                justify-content:center;
                cursor:pointer;
                color:var(--bb-muted) !important;
                background:rgba(255,255,255,.08) !important;
                border:1px solid rgba(255,255,255,.10) !important;
                font-family:'Space Grotesk',sans-serif;
                font-size:15px;
                font-weight:900;
                letter-spacing:-.08em;
                user-select:none;
            }
            #bb-sidebar-toggle-client:hover {
                color:var(--bb-text) !important;
                border-color:rgba(138,180,255,.28) !important;
                background:rgba(138,180,255,.14) !important;
            }
            body.bb-sidebar-collapsed section[data-testid="stSidebar"] {
                display:none !important;
                width:0 !important;
                min-width:0 !important;
                max-width:0 !important;
            }
            body.bb-sidebar-collapsed .block-container {
                max-width:1520px !important;
                padding-left:2.5rem !important;
                padding-right:2.5rem !important;
            }
            .bb-brand-mark {
                width:44px;
                height:44px;
                border-radius:16px;
                display:flex;
                align-items:center;
                justify-content:center;
                font-family:'Space Grotesk',sans-serif;
                font-size:15px;
                font-weight:700;
                letter-spacing:-.04em;
                color:#061426;
                background:linear-gradient(135deg, var(--bb-secondary), var(--bb-primary));
                box-shadow:0 14px 36px rgba(77,226,191,.18);
            }
            .bb-topbar-kicker, .bb-kicker, .bb-section-caption, .bb-label {
                font-family:'Space Grotesk',sans-serif;
                text-transform:uppercase;
                letter-spacing:.24em;
                font-size:10px;
                font-weight:700;
            }
            .bb-topbar-kicker {
                color:var(--bb-faint);
            }
            .bb-topbar-title {
                font-size:20px;
                font-weight:900;
                letter-spacing:-.05em;
                color:var(--bb-text);
            }
            .bb-session-pill, .bb-badge, .bb-chip {
                display:inline-flex;
                align-items:center;
                justify-content:center;
                border-radius:999px;
                min-height:32px;
                padding:0 12px;
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
            }
            .bb-session-pill {
                color:var(--bb-muted);
                background:rgba(255,255,255,.04);
                border:1px solid rgba(255,255,255,.06);
                max-width:220px;
                overflow:hidden;
                text-overflow:ellipsis;
                white-space:nowrap;
            }
            .bb-logout-link {
                display:inline-flex;
                align-items:center;
                justify-content:center;
                min-height:34px;
                padding:0 13px;
                border-radius:999px;
                color:var(--bb-text) !important;
                background:rgba(255,255,255,.05);
                border:1px solid rgba(255,255,255,.08);
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
            }
            .bb-logout-link:hover {
                border-color:rgba(255,143,143,.24);
                color:var(--bb-danger) !important;
            }
            .bb-logout-wrap {
                position:fixed;
                top:16px;
                right:20px;
                z-index:1001;
                width:auto;
            }
            .bb-logout-wrap .stButton > button {
                min-height:36px;
                padding:0 14px;
                border-radius:999px;
                font-size:10px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
                color:var(--bb-muted);
                background:rgba(255,255,255,.05);
                border:1px solid rgba(255,255,255,.08);
            }
            .bb-logout-wrap .stButton > button:hover {
                border-color:rgba(255,143,143,.24);
                color:var(--bb-danger);
            }
            .bb-badge {
                border:1px solid rgba(138,180,255,.22);
                background:rgba(138,180,255,.12);
                color:var(--bb-primary);
            }
            .bb-badge-positive {
                border-color:rgba(77,226,191,.20);
                background:rgba(77,226,191,.12);
                color:var(--bb-secondary);
            }
            .bb-badge-danger {
                border-color:rgba(255,143,143,.18);
                background:rgba(255,143,143,.12);
                color:var(--bb-danger);
            }
            .bb-badge-neutral {
                border-color:rgba(176,176,176,.18);
                background:rgba(176,176,176,.10);
                color:#b0b0b0;
            }
            .bb-chip {
                border:1px solid rgba(138,180,255,.16);
                background:rgba(138,180,255,.10);
                color:var(--bb-primary);
            }
            .bb-chip-secondary {
                border-color:rgba(77,226,191,.18);
                background:rgba(77,226,191,.10);
                color:var(--bb-secondary);
            }
            .bb-ghost-link {
                color:var(--bb-muted);
                font-size:12px;
                font-weight:700;
                padding:9px 12px;
                border-radius:12px;
                background:rgba(255,255,255,.04);
                border:1px solid rgba(255,255,255,.06);
            }
            .bb-hero {
                position:relative;
                overflow:hidden;
                padding:16px 20px;
                border-radius:22px;
                background:linear-gradient(180deg, rgba(18,26,36,.94), rgba(12,18,26,.94));
                border:1px solid rgba(138,180,255,.12);
                box-shadow:var(--bb-shadow);
                margin-bottom:.15rem;
            }
            .bb-hero::before,
            .bb-hero::after {
                content:"";
                position:absolute;
                border-radius:999px;
                pointer-events:none;
            }
            .bb-hero::before {
                top:-120px;
                right:-80px;
                width:260px;
                height:260px;
                background:radial-gradient(circle, rgba(138,180,255,.20), transparent 62%);
            }
            .bb-hero::after {
                bottom:-110px;
                left:-50px;
                width:220px;
                height:220px;
                background:radial-gradient(circle, rgba(77,226,191,.16), transparent 62%);
            }
            .bb-hero-secondary::before {
                background:radial-gradient(circle, rgba(77,226,191,.22), transparent 62%);
            }
            .bb-kicker {
                color:var(--bb-secondary);
                margin-bottom:8px;
            }
            .bb-title {
                position:relative;
                z-index:1;
                font-size:clamp(20px, 3.5vw, 30px);
                line-height:.98;
                font-weight:900;
                letter-spacing:-.06em;
                color:var(--bb-text);
                max-width:720px;
            }
            .bb-subtitle {
                position:relative;
                z-index:1;
                margin-top:6px;
                max-width:760px;
                color:var(--bb-muted);
                font-size:13px;
                line-height:1.6;
            }
            .bb-chip-row {
                position:relative;
                z-index:1;
                display:flex;
                flex-wrap:wrap;
                gap:10px;
                margin-top:10px;
            }
            .bb-section-head {
                display:flex;
                align-items:end;
                justify-content:space-between;
                gap:12px;
                margin:.25rem 0;
            }
            .bb-section-title {
                font-size:13px;
                font-weight:800;
                letter-spacing:.18em;
                text-transform:uppercase;
                color:var(--bb-faint);
            }
            .bb-section-caption {
                color:var(--bb-faint);
            }
            .bb-panel, .bb-metric-card {
                position:relative;
                overflow:hidden;
                background:linear-gradient(180deg, rgba(18,26,36,.92), rgba(12,18,26,.96));
                border:1px solid rgba(255,255,255,.06);
                border-radius:var(--bb-radius);
                box-shadow:var(--bb-shadow);
            }
            .bb-panel {
                padding:18px;
            }
            .bb-panel::after, .bb-metric-card::after {
                content:"";
                position:absolute;
                inset:0;
                background:linear-gradient(180deg, rgba(255,255,255,.03), transparent 40%);
                pointer-events:none;
            }
            .bb-panel-positive {
                border-color:rgba(77,226,191,.16);
            }
            .bb-panel-danger {
                border-color:rgba(255,143,143,.16);
            }
            .bb-panel-neutral {
                border-color:rgba(176,176,176,.12);
            }
            .bb-metric-card {
                min-height:140px;
                padding:20px;
            }
            .bb-metric-card::before {
                content:"";
                position:absolute;
                top:-32px;
                right:-28px;
                width:130px;
                height:130px;
                border-radius:999px;
                background:radial-gradient(circle, rgba(138,180,255,.18), transparent 65%);
            }
            .bb-metric-card-value {
                position:relative;
                margin-top:12px;
                color:var(--bb-text);
                font-size:34px;
                line-height:1;
                font-weight:900;
                letter-spacing:-.05em;
            }
            .bb-metric-card-subtitle {
                position:relative;
                margin-top:12px;
                color:var(--bb-muted);
                font-size:12px;
                line-height:1.6;
            }
            .bb-meter {
                position:relative;
                margin-top:12px;
                height:6px;
                border-radius:999px;
                background:rgba(255,255,255,.07);
                overflow:hidden;
            }
            .bb-meter-fill {
                height:100%;
                border-radius:999px;
                background:linear-gradient(90deg, var(--bb-secondary), var(--bb-primary));
            }
            .bb-metric-danger .bb-meter-fill {
                background:linear-gradient(90deg, var(--bb-danger), #ff5d5d);
            }
            .bb-stat-strip {
                display:flex;
                flex-wrap:wrap;
                gap:8px 22px;
                align-items:center;
                margin-bottom:12px;
                padding:10px 16px;
                border-radius:16px;
                background:rgba(255,255,255,.02);
                border:1px solid rgba(255,255,255,.05);
                font-family:'Space Grotesk',sans-serif;
            }
            .bb-stat-strip .bb-stat {
                display:flex;
                align-items:baseline;
                gap:7px;
                font-size:10px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
                color:var(--bb-faint);
            }
            .bb-stat-strip .bb-stat b {
                font-size:15px;
                letter-spacing:-.02em;
                color:var(--bb-text);
            }
            .bb-stat-strip .bb-stat b.up {
                color:var(--bb-secondary);
            }
            .bb-stat-strip .bb-stat b.down {
                color:var(--bb-danger);
            }
            .bb-metric-positive .bb-metric-card-value,
            .bb-text-positive {
                color:var(--bb-secondary);
            }
            .bb-metric-danger .bb-metric-card-value,
            .bb-text-danger {
                color:var(--bb-danger);
            }
            .bb-radar-card {
                background:linear-gradient(135deg, rgba(77,226,191,.06), rgba(18,26,36,.94));
                border:1px solid rgba(77,226,191,.14);
                border-left:3px solid var(--bb-secondary);
            }
            .bb-radar-card .bb-list-row-title {
                color:var(--bb-secondary);
            }
            .bb-table {
                width:100%;
                border-collapse:collapse;
                overflow:hidden;
                border-radius:22px;
                background:rgba(18,26,36,.84);
            }
            .bb-table th {
                text-align:left;
                padding:14px 16px;
                color:var(--bb-faint);
                font-size:11px;
                letter-spacing:.16em;
                text-transform:uppercase;
                background:rgba(255,255,255,.03);
            }
            .bb-table td {
                padding:14px 16px;
                color:var(--bb-text);
                font-size:14px;
                border-top:1px solid rgba(255,255,255,.05);
            }
            .bb-table code {
                color:var(--bb-primary);
                background:none;
                padding:0;
                font-weight:800;
            }
            .bb-list {
                display:grid;
                gap:12px;
            }
            .bb-list-row {
                display:flex;
                align-items:center;
                justify-content:space-between;
                gap:12px;
                padding:14px 16px;
                border-radius:18px;
                background:rgba(255,255,255,.03);
                border:1px solid rgba(255,255,255,.04);
            }
            .bb-list-row-title {
                font-weight:800;
                color:var(--bb-text);
                letter-spacing:-.03em;
            }
            .bb-list-row-subtitle, .bb-note {
                color:var(--bb-muted);
                font-size:12px;
                line-height:1.6;
            }
            .bb-note-strong {
                color:var(--bb-text);
                font-weight:700;
            }
            .bb-footer {
                display:flex;
                align-items:center;
                justify-content:center;
                flex-wrap:wrap;
                gap:8px;
                margin:2.5rem 0 1rem;
                padding-top:1rem;
                border-top:1px solid rgba(255,255,255,.06);
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
                color:var(--bb-faint);
            }
            .bb-footer-brand {
                color:var(--bb-muted);
            }
            .bb-footer-dot {
                width:8px;
                height:8px;
                border-radius:999px;
                display:inline-block;
            }
            .bb-footer-sep {
                opacity:.5;
            }
            .bb-footer-note {
                letter-spacing:.08em;
            }
            .st-key-footer_navigation {
                position:fixed;
                left:0;
                right:0;
                bottom:0;
                z-index:999;
                background:rgba(10,15,22,.94);
                backdrop-filter:blur(16px);
                -webkit-backdrop-filter:blur(16px);
                border-top:1px solid rgba(173,198,255,.12);
                box-shadow:0 -4px 24px rgba(0,0,0,.6);
                padding:8px max(1rem, calc((100vw - 1520px) / 2));
                pointer-events:auto !important;
            }
            .st-key-footer_navigation [data-testid="stHorizontalBlock"] {
                gap:8px;
            }
            .st-key-footer_navigation .stButton > button {
                min-height:34px;
                padding:6px 14px;
                border-radius:999px;
                font-family:'Space Grotesk',sans-serif;
                font-size:11px;
                font-weight:700;
                letter-spacing:.08em;
                text-transform:uppercase;
                white-space:nowrap;
                cursor:pointer !important;
            }
            .st-key-footer_navigation .stButton > button:hover {
                color:#ffffff !important;
                border-color:rgba(138,180,255,.45) !important;
                background:rgba(138,180,255,.14) !important;
            }
            .st-key-footer_navigation .stButton > button[kind="primary"] {
                color:#ffffff !important;
                border-color:var(--bb-secondary) !important;
                background:rgba(77,226,191,.16) !important;
                box-shadow:0 0 12px rgba(77,226,191,.2);
            }
            .bb-footer-meta {
                display:flex;
                align-items:center;
                justify-content:center;
                flex-wrap:wrap;
                gap:8px;
                margin-top:6px;
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.1em;
                text-transform:uppercase;
                color:var(--bb-faint);
                pointer-events:auto !important;
            }
            .st-key-footer_navigation .bb-footer-brand {
                color:var(--bb-secondary);
                font-weight:800;
                font-size:11px;
            }
            .st-key-footer_navigation .bb-footer-sep {
                color:rgba(176,191,216,.28);
                opacity:1;
            }
            .bb-footer-status {
                color:var(--bb-muted);
            }
            .bb-footer-copy {
                color:var(--bb-muted);
                font-size:10px;
            }
            .bb-footer-link {
                color:var(--bb-primary);
                cursor:pointer;
                text-decoration:none;
                pointer-events:auto !important;
            }
            .bb-footer-link:hover {
                color:#ffffff;
                text-decoration:underline;
            }
            .block-container {
                padding-bottom:150px;
            }
            @media (max-width: 900px) {
                .bb-footer-note {
                    display:none;
                }
                .block-container {
                    padding-bottom:170px;
                }
            }
            .bb-sidebar-shell {
                position:relative;
                top:auto;
                left:auto;
                width:100%;
                padding:14px;
                border-radius:24px;
                background:linear-gradient(180deg, rgba(13,19,31,.90), rgba(10,15,22,.86));
                border:1px solid rgba(255,255,255,.06);
                box-shadow:0 20px 52px rgba(0,0,0,.30);
                backdrop-filter:blur(20px);
            }
            .bb-sidebar-kicker {
                padding:4px 8px 12px;
                color:var(--bb-faint);
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.24em;
                text-transform:uppercase;
            }
            .bb-sidebar-note {
                padding:0 8px 12px;
                color:var(--bb-muted);
                font-size:12px;
                line-height:1.5;
            }
            section[data-testid="stSidebar"] .stButton > button {
                justify-content:flex-start;
                min-height:48px;
                border-radius:16px;
                font-family:'Space Grotesk',sans-serif;
                font-size:12px;
                font-weight:800;
                letter-spacing:.10em;
                text-transform:uppercase;
                background:rgba(255,255,255,.03);
                border:1px solid rgba(255,255,255,.05);
                color:var(--bb-muted);
            }
            section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
                color:#061426;
                background:linear-gradient(135deg, var(--bb-secondary), var(--bb-primary));
                border-color:transparent;
            }
            .bb-nav-icon {
                font-family:'Material Symbols Outlined';
                font-variation-settings:'FILL' 0, 'wght' 500, 'GRAD' 0, 'opsz' 24;
                font-size:18px;
                line-height:1;
            }
            .stButton > button, .stDownloadButton > button {
                min-height:48px;
                border-radius:18px;
                border:1px solid rgba(138,180,255,.14);
                background:linear-gradient(180deg, rgba(27,39,54,.95), rgba(18,26,36,.95));
                color:var(--bb-text);
                font-size:13px;
                font-weight:800;
                box-shadow:none;
            }
            .stButton > button[kind="primary"] {
                background:linear-gradient(135deg, var(--bb-primary), var(--bb-primary-strong));
                color:#041627;
                border-color:transparent;
            }
            .desktop-only {
                display:block;
            }
            .mobile-only {
                display:none;
            }
            .stTextInput label, .stNumberInput label, .stSelectbox label,
            .stTextArea label, .stSlider label, .stToggle label, .stSelectSlider label {
                color:var(--bb-muted) !important;
                font-size:12px !important;
                font-weight:700 !important;
            }
            .stTextInput input, .stNumberInput input, .stTextArea textarea,
            .stSelectbox [data-baseweb="select"], .stMultiSelect [data-baseweb="select"] {
                min-height:48px;
                background:rgba(8,13,20,.92) !important;
                color:var(--bb-text) !important;
                border:1px solid rgba(255,255,255,.07) !important;
                border-radius:18px !important;
            }
            .stSlider [data-baseweb="slider"] > div div,
            .stSlider [role="slider"],
            .stSelectSlider [role="slider"] {
                background:var(--bb-secondary) !important;
            }
            .stTabs [data-baseweb="tab-list"] {
                gap:.5rem;
                border-bottom:none;
                margin-bottom:.75rem;
            }
            .stTabs [data-baseweb="tab"] {
                min-height:44px;
                border-radius:999px;
                background:rgba(255,255,255,.03);
                border:1px solid rgba(255,255,255,.06);
                color:var(--bb-muted);
                font-weight:800;
                padding:0 16px;
            }
            .stTabs [aria-selected="true"] {
                color:var(--bb-secondary) !important;
                background:rgba(77,226,191,.10) !important;
                border-color:rgba(77,226,191,.18) !important;
            }
            .stAlert {
                border-radius:18px;
                border:1px solid rgba(255,255,255,.06);
                background:rgba(18,26,36,.9);
            }
            div[data-testid="stMetric"] {
                background:linear-gradient(180deg, rgba(18,26,36,.92), rgba(12,18,26,.96));
                border:1px solid rgba(255,255,255,.06);
                border-radius:22px;
                padding:1rem 1rem .9rem;
            }
            div[data-testid="stMetric"] label {
                color:var(--bb-faint) !important;
                text-transform:uppercase;
                letter-spacing:.14em;
                font-size:10px !important;
                font-weight:800 !important;
            }
            div[data-testid="stMetricValue"] {
                color:var(--bb-text);
                font-weight:900;
                letter-spacing:-.04em;
            }
            [data-testid="stPlotlyChart"] {
                background:linear-gradient(180deg, rgba(18,26,36,.92), rgba(12,18,26,.96));
                border:1px solid rgba(255,255,255,.06);
                border-radius:26px;
                padding:.5rem;
                overflow:hidden;
            }
            ::-webkit-scrollbar {
                width:6px;
                height:6px;
            }
            ::-webkit-scrollbar-track {
                background:transparent;
            }
            ::-webkit-scrollbar-thumb {
                background:rgba(138,180,255,.18);
                border-radius:999px;
            }
            ::-webkit-scrollbar-thumb:hover {
                background:rgba(138,180,255,.32);
            }
            section[data-testid="stSidebar"] {
                background:transparent !important;
                border-right:none !important;
            }
            section[data-testid="stSidebar"][aria-expanded="true"] {
                width:236px !important;
                min-width:236px !important;
                max-width:236px !important;
                flex-shrink:0 !important;
            }
            section[data-testid="stSidebar"][aria-expanded="true"] > div {
                background:transparent !important;
                width:236px !important;
                min-width:236px !important;
                max-width:236px !important;
            }
            section[data-testid="stSidebar"][aria-expanded="true"] div[data-testid="stSidebarContent"] {
                width:236px !important;
                min-width:236px !important;
                max-width:236px !important;
            }
            @media (max-width: 900px) {
                .block-container {
                    padding:7.5rem .9rem 3rem;
                }
                .bb-topnav {
                    display:none;
                }
                section[data-testid="stSidebar"][aria-expanded="true"],
                section[data-testid="stSidebar"][aria-expanded="true"] > div,
                section[data-testid="stSidebar"][aria-expanded="true"] div[data-testid="stSidebarContent"] {
                    min-width:236px !important;
                    width:236px !important;
                    max-width:236px !important;
                }
                .desktop-only {
                    display:none !important;
                }
                .mobile-only {
                    display:block !important;
                }
                .bb-topbar {
                    height:64px;
                    padding:0 14px;
                }
                .bb-topbar-actions {
                    gap:8px;
                }
                .bb-session-pill {
                    display:none;
                }
                .bb-logout-wrap {
                    top:14px;
                    right:14px;
                }
                .bb-sidebar-shell {
                    margin:0 0 1rem;
                    padding:10px;
                    border-radius:22px;
                }
                .bb-sidebar-kicker {
                    display:none;
                }
                section[data-testid="stSidebar"] .stButton > button {
                    min-height:46px;
                    font-size:10px;
                    letter-spacing:.08em;
                }
                .bb-panel, .bb-metric-card, .bb-hero {
                    border-radius:24px;
                }
            }
            @media (max-width: 640px) {
                section[data-testid="stSidebar"][aria-expanded="true"],
                section[data-testid="stSidebar"][aria-expanded="true"] > div,
                section[data-testid="stSidebar"][aria-expanded="true"] div[data-testid="stSidebarContent"] {
                    min-width:208px !important;
                    width:208px !important;
                    max-width:208px !important;
                }
                .block-container {
                    padding-left:.7rem;
                    padding-right:.7rem;
                }
                .bb-title {
                    max-width:100%;
                }
                .bb-ghost-link {
                    padding:8px 10px;
                    font-size:11px;
                }
                section[data-testid="stSidebar"] .stButton > button {
                    min-height:44px;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
