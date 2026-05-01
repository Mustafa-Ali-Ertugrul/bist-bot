"""Visual style helpers for the Streamlit runtime."""

from __future__ import annotations

import streamlit as st


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
            [data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu,
            section[data-testid="stSidebar"] {
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
                max-width:1280px;
                padding:6.2rem 1rem 7.25rem;
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
                height:76px;
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
                padding:28px 24px;
                border-radius:30px;
                background:linear-gradient(180deg, rgba(18,26,36,.94), rgba(12,18,26,.94));
                border:1px solid rgba(138,180,255,.12);
                box-shadow:var(--bb-shadow);
                margin-bottom:.35rem;
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
                font-size:clamp(28px, 6vw, 46px);
                line-height:.98;
                font-weight:900;
                letter-spacing:-.06em;
                color:var(--bb-text);
                max-width:720px;
            }
            .bb-subtitle {
                position:relative;
                z-index:1;
                margin-top:12px;
                max-width:760px;
                color:var(--bb-muted);
                font-size:14px;
                line-height:1.72;
            }
            .bb-chip-row {
                position:relative;
                z-index:1;
                display:flex;
                flex-wrap:wrap;
                gap:10px;
                margin-top:18px;
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
            .bb-metric-positive .bb-metric-card-value,
            .bb-text-positive {
                color:var(--bb-secondary);
            }
            .bb-metric-danger .bb-metric-card-value,
            .bb-text-danger {
                color:var(--bb-danger);
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
            .bb-mobile-nav-shell {
                position:fixed;
                left:50%;
                bottom:14px;
                transform:translateX(-50%);
                z-index:1000;
                width:min(760px, calc(100vw - 24px));
                display:grid;
                grid-template-columns:repeat(4, minmax(0, 1fr));
                gap:8px;
                padding:10px 12px;
                border-radius:24px;
                background:rgba(12,18,31,.90);
                border:1px solid rgba(255,255,255,.10);
                box-shadow:0 16px 40px rgba(0,0,0,.34);
                backdrop-filter:blur(20px);
            }
            .bb-bottomnav-spacer {
                height:88px;
            }
            .bb-nav-link {
                display:flex;
                flex-direction:column;
                align-items:center;
                justify-content:center;
                gap:6px;
                min-height:56px;
                border-radius:18px;
                border:1px solid rgba(138,180,255,.14);
                background:linear-gradient(180deg, rgba(27,39,54,.95), rgba(18,26,36,.95));
                color:var(--bb-text) !important;
                font-size:13px;
                font-weight:800;
                box-shadow:none;
                text-decoration:none;
                transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
            }
            .bb-nav-link:hover {
                transform:translateY(-1px);
                border-color:rgba(138,180,255,.30);
                box-shadow:0 10px 24px rgba(0,0,0,.22);
            }
            .bb-nav-link-active {
                background:linear-gradient(135deg, var(--bb-primary), var(--bb-primary-strong));
                color:#041627 !important;
                border-color:transparent;
                box-shadow:0 12px 30px rgba(75,142,255,.30);
            }
            .bb-nav-icon {
                font-family:'Material Symbols Outlined';
                font-variation-settings:'FILL' 0, 'wght' 500, 'GRAD' 0, 'opsz' 24;
                font-size:18px;
                line-height:1;
            }
            .bb-nav-label {
                font-family:'Space Grotesk',sans-serif;
                font-size:10px;
                font-weight:700;
                letter-spacing:.14em;
                text-transform:uppercase;
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
            @media (max-width: 900px) {
                .block-container {
                    padding-top:6rem;
                    padding-bottom:7rem;
                }
                .bb-topbar {
                    height:72px;
                    padding:0 14px;
                }
                .bb-topbar-actions {
                    gap:8px;
                }
                .bb-session-pill {
                    display:none;
                }
                .bb-panel, .bb-metric-card, .bb-hero {
                    border-radius:24px;
                }
            }
            @media (max-width: 640px) {
                .block-container {
                    padding-left:.7rem;
                    padding-right:.7rem;
                }
                .bb-title {
                    max-width:100%;
                }
                .bb-bottomnav {
                    bottom:10px;
                    width:calc(100vw - 14px);
                    border-radius:24px;
                    padding:8px;
                }
                .bb-nav-item {
                    min-height:54px;
                    font-size:9px;
                    letter-spacing:.1em;
                }
                .bb-ghost-link {
                    padding:8px 10px;
                    font-size:11px;
                }
                .bb-mobile-nav-shell {
                    bottom:10px;
                    width:calc(100vw - 14px);
                    border-radius:24px;
                    padding:8px;
                }
                .bb-bottomnav-spacer {
                    height:82px;
                }
                .bb-nav-link {
                    min-height:54px;
                }
                .bb-nav-label {
                    font-size:9px;
                    letter-spacing:.1em;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
