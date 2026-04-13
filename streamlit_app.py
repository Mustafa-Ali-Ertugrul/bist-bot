import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import config
from data_fetcher import BISTDataFetcher
from indicators import TechnicalIndicators
from strategy import StrategyEngine
from streamlit_utils import check_signals, send_signal_notification

st.set_page_config(
    page_title="BIST Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def bootstrap_state():
    defaults = {
        "data_fetcher": BISTDataFetcher(),
        "engine": StrategyEngine(),
        "signals": [],
        "all_data": {},
        "auto_refresh": False,
        "refresh_interval": 5,
        "min_score_filter": -100,
        "rsi_min_filter": 0,
        "rsi_max_filter": 100,
        "vol_ratio_filter": 0.0,
        "notify_min_score": 30,
        "notify_telegram": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
        "ind_rsi_period":    config.RSI_PERIOD,
        "ind_rsi_oversold":  config.RSI_OVERSOLD,
        "ind_rsi_overbought":config.RSI_OVERBOUGHT,
        "ind_sma_fast":      config.SMA_FAST,
        "ind_sma_slow":      config.SMA_SLOW,
        "ind_ema_fast":      config.EMA_FAST,
        "ind_ema_slow":      config.EMA_SLOW,
        "ind_macd_fast":     config.MACD_FAST,
        "ind_macd_slow":    config.MACD_SLOW,
        "ind_macd_signal":  config.MACD_SIGNAL,
        "ind_bb_period":    config.BOLLINGER_PERIOD,
        "ind_bb_std":       float(config.BOLLINGER_STD),
        "ind_adx_threshold": config.ADX_THRESHOLD,
        "tg_token_input":   config.TELEGRAM_BOT_TOKEN or "",
        "tg_chat_input":    config.TELEGRAM_CHAT_ID or "",
        "deploy_confirmed": False,
        "last_scan_time": None,
        "current_view": "dashboard",
        "selected_ticker": config.WATCHLIST[0],
        "analysis_period": "6mo",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    view_param = st.query_params.get("view", st.session_state.current_view)
    if view_param in {"dashboard", "signals", "analysis", "settings"}:
        st.session_state.current_view = view_param


def inject_styles():
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
            * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
            section[data-testid="stSidebar"] {display:none !important;}
            [data-testid="stHeader"] {display:none !important;}
            [data-testid="stToolbar"] {display:none !important;}
            footer {display:none !important;}
            .viewerBadge_container {display:none !important;}
            #MainMenu {display:none !important;}
            .block-container {max-width:1240px;padding-top:1.2rem;padding-bottom:7rem;}
            .stApp {
                background:
                    radial-gradient(circle at top right, rgba(72,221,188,0.08), transparent 22%),
                    radial-gradient(circle at top left, rgba(173,198,255,0.10), transparent 24%),
                    linear-gradient(180deg, #0b1016 0%, #10141a 100%);
            }
            .hero-shell, .surface-shell, .metric-shell {
                border:1px solid rgba(255,255,255,0.06);
                box-shadow:0 24px 80px rgba(0,0,0,0.22);
            }
            .hero-shell {
                background:linear-gradient(135deg, rgba(24,28,34,0.94), rgba(16,20,26,0.98));
                border-radius:26px;
                padding:28px;
                overflow:hidden;
                position:relative;
                margin-bottom:18px;
            }
            .hero-shell:after {
                content:"";
                position:absolute;
                inset:0;
                background:radial-gradient(circle at 88% 18%, rgba(72,221,188,0.12), transparent 20%);
                pointer-events:none;
            }
            .surface-shell {
                background:rgba(28,32,38,0.92);
                border-radius:22px;
                padding:20px;
            }
            .metric-shell {
                background:linear-gradient(180deg, rgba(28,32,38,0.96), rgba(20,24,30,0.98));
                border-radius:22px;
                padding:18px 20px;
                min-height:132px;
            }
            .eyebrow {color:#48ddbc;font-size:11px;font-weight:800;letter-spacing:0.22em;text-transform:uppercase;}
            .hero-title {font-size:42px;font-weight:900;letter-spacing:-0.04em;color:#dfe2eb;line-height:1.0;margin:10px 0 8px;}
            .hero-copy {color:#99a2b2;font-size:14px;line-height:1.7;max-width:620px;}
            .pill-stat {display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:rgba(255,255,255,0.04);color:#c1c6d7;border:1px solid rgba(255,255,255,0.05);font-size:12px;margin-right:8px;margin-top:8px;}
            .metric-kicker {color:#8b90a0;text-transform:uppercase;letter-spacing:0.18em;font-size:10px;font-weight:800;}
            .metric-value {font-size:34px;font-weight:900;letter-spacing:-0.04em;color:#dfe2eb;margin-top:8px;}
            .metric-sub {color:#99a2b2;font-size:12px;margin-top:8px;}
            .section-title {font-size:24px;font-weight:850;letter-spacing:-0.03em;color:#dfe2eb;margin:12px 0 14px;}
            .list-row {padding:14px 0;border-bottom:1px solid rgba(255,255,255,0.05);}
            .list-row:last-child {border-bottom:none;}
            .signal-chip {display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;}
            .signal-chip.buy {background:rgba(72,221,188,0.12);color:#48ddbc;}
            .signal-chip.sell {background:rgba(255,180,170,0.12);color:#ffb4aa;}
            .footer-note {color:#738091;font-size:12px;text-align:center;margin-top:20px;}
            .bottom-nav {
                position: fixed;
                left: 50%;
                bottom: 10px;
                transform: translateX(-50%);
                width: min(840px, calc(100vw - 16px));
                background: linear-gradient(180deg, rgba(20,24,30,0.97), rgba(12,16,22,0.98));
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 24px;
                backdrop-filter: blur(24px);
                box-shadow: 0 24px 70px rgba(0,0,0,0.45);
                padding: 10px 12px max(10px, env(safe-area-inset-bottom));
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                z-index: 9999;
            }
            .bottom-nav a {
                text-decoration: none;
                color: #9aa4b2;
                border-radius: 18px;
                padding: 12px 6px 10px;
                text-align: center;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.16em;
                text-transform: uppercase;
                transition: all 0.18s ease;
                border: 1px solid rgba(255,255,255,0.04);
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 7px;
                min-height: 62px;
            }
            .bottom-nav a.active {
                background: linear-gradient(180deg, rgba(72,221,188,0.14), rgba(72,221,188,0.08));
                color: #48ddbc;
                border-color: rgba(72,221,188,0.22);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
            }
            .bottom-nav-icon {
                font-size: 20px;
                line-height: 1;
                letter-spacing: normal;
                display: block;
            }
            .signal-card-buy {
                border: 1px solid rgba(72, 221, 188, 0.25);
                box-shadow: 0 0 24px rgba(72, 221, 188, 0.08), 0 8px 32px rgba(0,0,0,0.20);
                border-radius: 20px;
                padding: 20px;
                background: rgba(72, 221, 188, 0.04);
                margin-bottom: 12px;
            }
            .signal-card-sell {
                border: 1px solid rgba(255, 121, 108, 0.25);
                box-shadow: 0 0 24px rgba(255, 121, 108, 0.08), 0 8px 32px rgba(0,0,0,0.20);
                border-radius: 20px;
                padding: 20px;
                background: rgba(255, 121, 108, 0.04);
                margin-bottom: 12px;
            }
            .signal-card-neutral {
                border: 1px solid rgba(255,255,255,0.07);
                box-shadow: 0 8px 32px rgba(0,0,0,0.20);
                border-radius: 20px;
                padding: 20px;
                background: rgba(255,255,255,0.02);
                margin-bottom: 12px;
            }
            .score-bar-wrap {
                background: rgba(255,255,255,0.06);
                border-radius: 999px;
                height: 6px;
                width: 100%;
                margin-top: 8px;
                overflow: hidden;
            }
            .score-bar-fill {
                height: 6px;
                border-radius: 999px;
                background: linear-gradient(90deg, #48ddbc, #2dd4bf);
                transition: width 0.4s ease;
            }
            .score-bar-fill.negative {
                background: linear-gradient(90deg, #ff796c, #ef4444);
            }
            .reason-chip {
                display: inline-block;
                padding: 4px 10px;
                border-radius: 999px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.08);
                color: #a0aabb;
                font-size: 11px;
                font-weight: 600;
                margin: 3px 3px 0 0;
            }
            .verdict-card {
                border-radius: 22px;
                padding: 24px;
                text-align: center;
                margin-bottom: 16px;
            }
            .verdict-card.buy {
                background: linear-gradient(135deg, rgba(72,221,188,0.10), rgba(45,212,191,0.06));
                border: 1px solid rgba(72,221,188,0.22);
                box-shadow: 0 0 40px rgba(72,221,188,0.10);
            }
            .verdict-card.sell {
                background: linear-gradient(135deg, rgba(255,121,108,0.10), rgba(239,68,68,0.06));
                border: 1px solid rgba(255,121,108,0.22);
                box-shadow: 0 0 40px rgba(255,121,108,0.10);
            }
            .verdict-label {
                font-size: 32px;
                font-weight: 900;
                letter-spacing: -0.03em;
                color: #dfe2eb;
            }
            .verdict-score {
                font-size: 14px;
                color: #8b90a0;
                margin-top: 6px;
            }
            .indicator-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 0;
                border-bottom: 1px solid rgba(255,255,255,0.04);
                font-size: 13px;
            }
            .indicator-row:last-child { border-bottom: none; }
            .indicator-name { color: #8b90a0; font-weight: 600; }
            .indicator-value { color: #dfe2eb; font-weight: 700; }
            .indicator-badge {
                padding: 3px 9px;
                border-radius: 999px;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.10em;
                text-transform: uppercase;
            }
            .indicator-badge.oversold { background: rgba(72,221,188,0.12); color: #48ddbc; }
            .indicator-badge.overbought { background: rgba(255,121,108,0.12); color: #ff796c; }
            .indicator-badge.neutral { background: rgba(255,255,255,0.06); color: #8b90a0; }
            .settings-group {
                background: rgba(28,32,38,0.92);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 20px;
                padding: 20px;
                margin-bottom: 14px;
            }
            .settings-group-title {
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0.14em;
                text-transform: uppercase;
                color: #48ddbc;
                margin-bottom: 14px;
            }
            .portfolio-hero {
                background: linear-gradient(135deg, rgba(18,22,30,0.97) 0%, rgba(24,28,36,0.95) 100%);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 26px;
                padding: 28px 32px;
                margin-bottom: 20px;
                position: relative;
                overflow: hidden;
            }
            .portfolio-hero::after {
                content: "";
                position: absolute;
                top: -40px; right: -40px;
                width: 220px; height: 220px;
                background: radial-gradient(circle, rgba(72,221,188,0.10), transparent 70%);
                pointer-events: none;
            }
            .portfolio-total {
                font-size: 48px;
                font-weight: 900;
                letter-spacing: -0.05em;
                color: #dfe2eb;
                line-height: 1.0;
            }
            .portfolio-label {
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.20em;
                text-transform: uppercase;
                color: #48ddbc;
                margin-bottom: 8px;
            }
            .portfolio-sub {
                font-size: 13px;
                color: #8b90a0;
                margin-top: 8px;
            }
            .pnl-positive { color: #48ddbc; font-weight: 800; }
            .pnl-negative { color: #ff796c; font-weight: 800; }

            .index-card {
                background: rgba(28,32,40,0.92);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 18px;
                padding: 16px 18px;
                margin-bottom: 10px;
            }
            .index-card-name {
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.16em;
                text-transform: uppercase;
                color: #8b90a0;
            }
            .index-card-value {
                font-size: 22px;
                font-weight: 900;
                letter-spacing: -0.03em;
                color: #dfe2eb;
                margin-top: 4px;
            }
            .index-card-change {
                font-size: 12px;
                font-weight: 700;
                margin-top: 4px;
            }
            .change-up { color: #48ddbc; }
            .change-down { color: #ff796c; }

            .live-insights-row {
                display: flex;
                align-items: flex-start;
                gap: 10px;
                padding: 12px 0;
                border-bottom: 1px solid rgba(255,255,255,0.04);
            }
            .live-insights-row:last-child { border-bottom: none; }
            .insight-dot {
                width: 8px; height: 8px;
                border-radius: 50%;
                margin-top: 5px;
                flex-shrink: 0;
            }
            .insight-dot.green { background: #48ddbc; box-shadow: 0 0 8px rgba(72,221,188,0.5); }
            .insight-dot.red   { background: #ff796c; box-shadow: 0 0 8px rgba(255,121,108,0.5); }
            .insight-dot.blue  { background: #adc6ff; box-shadow: 0 0 8px rgba(173,198,255,0.4); }
            .insight-text { font-size: 13px; color: #c1c6d7; line-height: 1.5; }
            .insight-time { font-size: 10px; color: #5a6270; margin-top: 2px; }
            .stock-identity {
                background: rgba(24,28,36,0.95);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 22px;
                padding: 22px 24px;
                margin-bottom: 18px;
                display: flex;
                align-items: center;
                gap: 20px;
            }
            .stock-logo-placeholder {
                width: 52px; height: 52px;
                border-radius: 14px;
                background: linear-gradient(135deg, rgba(72,221,188,0.15), rgba(45,212,191,0.08));
                border: 1px solid rgba(72,221,188,0.20);
                display: flex; align-items: center; justify-content: center;
                font-size: 18px; font-weight: 900; color: #48ddbc;
                flex-shrink: 0;
            }
            .stock-identity-name {
                font-size: 24px; font-weight: 900;
                letter-spacing: -0.03em; color: #dfe2eb;
            }
            .stock-identity-full {
                font-size: 13px; color: #8b90a0; margin-top: 2px;
            }
            .stock-identity-meta {
                display: flex; gap: 16px; margin-top: 8px; flex-wrap: wrap;
            }
            .stock-meta-pill {
                font-size: 11px; font-weight: 700;
                color: #99a2b2;
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 999px;
                padding: 4px 10px;
            }

            .mini-info-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 10px;
                margin-bottom: 14px;
            }
            .mini-info-card {
                background: rgba(28,32,40,0.92);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
                padding: 12px 14px;
            }
            .mini-info-label {
                font-size: 10px; font-weight: 800;
                letter-spacing: 0.16em; text-transform: uppercase;
                color: #5a6270;
            }
            .mini-info-value {
                font-size: 16px; font-weight: 800;
                color: #dfe2eb; margin-top: 4px;
            }
            .mini-info-sub {
                font-size: 10px; color: #8b90a0; margin-top: 2px;
            }

            .indicator-table {
                background: rgba(24,28,36,0.95);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 18px;
                padding: 16px 18px;
            }
            .indicator-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 0;
                border-bottom: 1px solid rgba(255,255,255,0.04);
                font-size: 13px;
            }
            .indicator-row:last-child { border-bottom: none; }
            .indicator-name { color: #8b90a0; font-weight: 600; }
            .indicator-value { color: #dfe2eb; font-weight: 700; }
            .indicator-badge {
                padding: 3px 9px; border-radius: 999px;
                font-size: 10px; font-weight: 800;
                letter-spacing: 0.10em; text-transform: uppercase;
            }
            .indicator-badge.oversold  { background: rgba(72,221,188,0.12); color: #48ddbc; }
            .indicator-badge.overbought{ background: rgba(255,121,108,0.12); color: #ff796c; }
            .indicator-badge.neutral   { background: rgba(255,255,255,0.06); color: #8b90a0; }
            .indicator-badge.bullish   { background: rgba(173,198,255,0.12); color: #adc6ff; }
            .indicator-badge.bearish   { background: rgba(255,121,108,0.12); color: #ff796c; }
            .settings-group {
                background: rgba(24,28,36,0.95);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 20px;
                padding: 20px 22px;
                margin-bottom: 14px;
            }
            .settings-group-title {
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.20em;
                text-transform: uppercase;
                color: #48ddbc;
                margin-bottom: 16px;
            }
            .risk-card {
                background: rgba(28,32,40,0.92);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 16px;
                padding: 16px 18px;
                margin-bottom: 10px;
            }
            .risk-card-title {
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.14em;
                text-transform: uppercase;
                color: #8b90a0;
                margin-bottom: 6px;
            }
            .risk-card-value {
                font-size: 22px;
                font-weight: 900;
                letter-spacing: -0.03em;
                color: #dfe2eb;
            }
            .risk-card-sub {
                font-size: 11px;
                color: #5a6270;
                margin-top: 4px;
            }
            .deploy-btn-wrap {
                background: linear-gradient(135deg, rgba(72,221,188,0.10), rgba(45,212,191,0.06));
                border: 1px solid rgba(72,221,188,0.22);
                border-radius: 18px;
                padding: 20px;
                margin-top: 16px;
                text-align: center;
            }
            .deploy-title {
                font-size: 14px;
                font-weight: 800;
                color: #48ddbc;
                margin-bottom: 6px;
            }
            .deploy-sub {
                font-size: 12px;
                color: #8b90a0;
                margin-bottom: 14px;
            }
            .param-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 0;
                border-bottom: 1px solid rgba(255,255,255,0.04);
                font-size: 13px;
            }
            .param-row:last-child { border-bottom: none; }
            .param-name  { color: #8b90a0; font-weight: 600; }
            .param-value { color: #dfe2eb; font-weight: 800; }
            .param-changed {
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: #48ddbc;
                margin-left: 8px;
            }
            @media (max-width: 768px) {
                .block-container {padding-left:0.8rem;padding-right:0.8rem;}
                .hero-shell {padding:20px;border-radius:20px;}
                .hero-title {font-size:32px;}
                .bottom-nav {bottom: 8px; width: calc(100vw - 12px); border-radius: 20px; padding-left: 8px; padding-right: 8px;}
                .bottom-nav a {min-height: 58px; padding-top: 10px; font-size: 9px;}
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def get_signal_color(signal_type):
    value = signal_type.value
    if "AL" in value:
        return "green"
    if "SAT" in value:
        return "red"
    return "blue"


def run_scan():
    fetcher = st.session_state.data_fetcher
    engine = st.session_state.engine
    fetcher.clear_cache()
    all_data = fetcher.fetch_all()
    signals = engine.scan_all(all_data)
    for ticker, df in all_data.items():
        signal_type, conditions = check_signals(ticker, df)
        if signal_type:
            send_signal_notification(ticker, signal_type, conditions)
    st.session_state.all_data = all_data
    st.session_state.signals = signals
    st.session_state.last_scan_time = datetime.now()


def ensure_initial_data():
    if st.session_state.signals:
        return
    try:
        run_scan()
        st.rerun()
    except Exception as exc:
        st.error(f"Tarama hatasi: {exc}")


def fetch_stock_news(ticker, max_results=5):
    name = config.TICKER_NAMES.get(ticker, ticker.replace(".IS", ""))
    all_news = []
    sources = [
        ("Google Haberler", f"https://news.google.com/rss/search?q={name}+hisse+senedi&hl=tr&gl=TR&ceid=TR:tr", "google"),
        ("Investing.com", f"https://tr.investing.com/search/?q={name}", "static"),
        ("Bloomberg HT", f"https://www.bloomberght.com/search?q={name}", "static"),
        ("TradingView", f"https://www.tradingview.com/symbols/{ticker.replace('.IS', '')}/ideas/", "static"),
    ]
    for source, url, source_type in sources:
        try:
            if source_type == "google":
                response = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
                items = re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>", response.text, re.DOTALL)
                for title, link in items[:max_results]:
                    text = title.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                    if len(text) > 10:
                        all_news.append({"title": text, "url": link, "source": source})
            else:
                all_news.append({"title": f"{name} - {source} sayfasi", "url": url, "source": source})
        except Exception:
            pass
    return all_news[: max_results + 2]


def get_market_summary(signals, all_data):
    if not signals or not all_data:
        return {}
    ti = TechnicalIndicators()
    sector_data = {}
    rsi_values = []
    vol_ratios = []
    for ticker, df in all_data.items():
        try:
            df_ind = ti.add_all(df.copy())
            last = df_ind.iloc[-1]
            rsi = last.get("rsi", 50)
            vol = last.get("volume_ratio", 1.0)
            rsi_values.append(rsi)
            vol_ratios.append(vol)
            if rsi < 30:
                sector_data["Asırı Satım"] = sector_data.get("Asırı Satım", 0) + 1
            elif rsi > 70:
                sector_data["Asırı Alım"] = sector_data.get("Asırı Alım", 0) + 1
            else:
                sector_data["Nötr"] = sector_data.get("Nötr", 0) + 1
        except Exception:
            pass
    return {
        "sector_dist": sector_data,
        "avg_rsi": sum(rsi_values) / len(rsi_values) if rsi_values else 50,
        "avg_vol_ratio": sum(vol_ratios) / len(vol_ratios) if vol_ratios else 1.0,
        "total_analyzed": len(rsi_values),
    }


@st.cache_data(ttl=180)
def fetch_index_data():
    try:
        import yfinance as yf

        tickers = {"XU100": "XU100.IS", "XU030": "XU030.IS", "USDTRY": "USDTRY=X"}
        result = {}
        for name, ticker in tickers.items():
            try:
                df = yf.download(ticker, period="2d", interval="1d", progress=False, auto_adjust=True)
                if df is not None and len(df) >= 2:
                    prev = float(df["Close"].iloc[-2])
                    last = float(df["Close"].iloc[-1])
                    chg = ((last - prev) / prev) * 100
                    result[name] = {"value": last, "change_pct": chg}
                else:
                    result[name] = {"value": 0.0, "change_pct": 0.0}
            except Exception:
                result[name] = {"value": 0.0, "change_pct": 0.0}
        return result
    except Exception:
        return {}


def render_portfolio_hero(signals, summary):
    strong_count = len([s for s in signals if s.score >= 40])
    buy_count = len([s for s in signals if s.score >= 10])
    sell_count = len([s for s in signals if s.score < 0])
    total = len(signals)
    success_rate = round((buy_count / total * 100) if total > 0 else 0)
    avg_rsi = summary.get("avg_rsi", 50)
    analyzed = summary.get("total_analyzed", len(config.WATCHLIST))
    scan_time = st.session_state.last_scan_time.strftime("%H:%M") if st.session_state.last_scan_time else "-"

    if avg_rsi < 40:
        mood, mood_color = "Asiri Satim Bolgesi", "#48ddbc"
    elif avg_rsi > 60:
        mood, mood_color = "Asiri Alim Bolgesi", "#ff796c"
    else:
        mood, mood_color = "Notr Bolge", "#adc6ff"

    st.markdown(
        f"""
    <div class="portfolio-hero">
      <div class="portfolio-label">BIST Bot Terminal</div>
      <div class="portfolio-total">
        {total}
        <span style='font-size:22px;color:#8b90a0;font-weight:600;'>sinyal</span>
      </div>
      <div class="portfolio-sub">
        <span class="pnl-positive">▲ {strong_count} guclu al</span>
        &nbsp;·&nbsp;
        <span style="color:#8b90a0;">{buy_count} pozitif</span>
        &nbsp;·&nbsp;
        <span class="pnl-negative">▼ {sell_count} satis</span>
        &nbsp;·&nbsp;
        <span style="color:{mood_color};">{mood} (RSI {avg_rsi:.0f})</span>
      </div>
      <div style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;">
        <span class="pill-stat">📊 {analyzed} hisse tarandi</span>
        <span class="pill-stat">🎯 Basari orani {success_rate}%</span>
        <span class="pill-stat">🕐 Son guncelleme {scan_time}</span>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def render_index_cards():
    index_data = fetch_index_data()
    if not index_data:
        return
    for name, data in index_data.items():
        value = data.get("value", 0.0)
        change = data.get("change_pct", 0.0)
        css = "change-up" if change >= 0 else "change-down"
        arrow = "▲" if change >= 0 else "▼"
        val_str = f"{value:,.0f}" if value > 100 else f"{value:.4f}"
        st.markdown(
            f"""
        <div class="index-card">
          <div class="index-card-name">{name}</div>
          <div class="index-card-value">{val_str}</div>
          <div class="index-card-change {css}">{arrow} {abs(change):.2f}%</div>
        </div>
        """,
            unsafe_allow_html=True,
        )


def render_live_insights(signals):
    if not signals:
        return
    top = sorted(signals, key=lambda s: abs(s.score), reverse=True)[:5]
    rows = []
    for s in top:
        name = config.TICKER_NAMES.get(s.ticker, s.ticker)
        ticker_short = s.ticker.replace(".IS", "")
        if s.score >= 40:
            dot, action = "green", "Guclu alim sinyali"
        elif s.score >= 10:
            dot, action = "blue", "Alim firsati"
        else:
            dot, action = "red", "Satis baskisi"
        time_str = st.session_state.last_scan_time.strftime("%H:%M") if st.session_state.last_scan_time else "-"
        rows.append(
            f"""
        <div class="live-insights-row">
          <div class="insight-dot {dot}"></div>
          <div>
            <div class="insight-text">
              <strong>{ticker_short}</strong> - {name}
              &nbsp;·&nbsp; {action}
              &nbsp;<span style='color:#8b90a0;'>Skor {s.score:+.0f}</span>
            </div>
            <div class="insight-time">{time_str}</div>
          </div>
        </div>
        """
        )
    st.markdown(f"<div class='surface-shell'>{''.join(rows)}</div>", unsafe_allow_html=True)


def render_stock_identity(ticker, snapshot):
    name = config.TICKER_NAMES.get(ticker, ticker)
    short = ticker.replace(".IS", "")
    price = snapshot.get("close", 0)
    change_pct = snapshot.get("change_pct", 0)
    volume_ratio = snapshot.get("volume_ratio", 1.0)
    atr = snapshot.get("atr", 0)
    support = snapshot.get("support", 0)
    resistance = snapshot.get("resistance", 0)

    change_color = "#48ddbc" if float(change_pct) >= 0 else "#ff796c"
    arrow = "▲" if float(change_pct) >= 0 else "▼"

    st.markdown(
        f"""
    <div class="stock-identity">
      <div class="stock-logo-placeholder">{short[:2]}</div>
      <div style="flex:1;">
        <div class="stock-identity-name">
          {short}
          <span style="font-size:14px;color:{change_color};margin-left:12px;">
            {arrow} {abs(float(change_pct)):.2f}%
          </span>
        </div>
        <div class="stock-identity-full">{name}</div>
        <div class="stock-identity-meta">
          <span class="stock-meta-pill">₺{float(price):.2f} fiyat</span>
          <span class="stock-meta-pill">Hacim {float(volume_ratio):.1f}x</span>
          <span class="stock-meta-pill">ATR ₺{float(atr):.2f}</span>
          <span class="stock-meta-pill">Destek ₺{float(support):.2f}</span>
          <span class="stock-meta-pill">Direnç ₺{float(resistance):.2f}</span>
        </div>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def render_verdict_card(signal):
    if signal is None:
        st.markdown(
            """
        <div class="verdict-card" style="background:rgba(255,255,255,0.02);
          border:1px solid rgba(255,255,255,0.06);border-radius:22px;
          padding:24px;text-align:center;">
          <div style="font-size:18px;color:#8b90a0;">Sinyal hesaplanamadı</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        return

    card_class = "buy" if signal.score >= 10 else "sell"
    score_color = "#48ddbc" if signal.score >= 0 else "#ff796c"
    bar_width = int((signal.score + 100) / 2)
    bar_class = "score-bar-fill" if signal.score >= 0 else "score-bar-fill negative"

    reason_chips = "".join(
        f"<span class='reason-chip'>{r[:55]}</span>"
        for r in signal.reasons[:5]
    )

    st.markdown(
        f"""
    <div class="verdict-card {card_class}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;
                  flex-wrap:wrap;gap:16px;">
        <div>
          <div style="font-size:11px;font-weight:800;letter-spacing:0.18em;
                      text-transform:uppercase;color:#8b90a0;margin-bottom:8px;">
            Oracle Kararı
          </div>
          <div class="verdict-label">{signal.signal_type.value}</div>
          <div class="verdict-score">
            Güven: {signal.confidence}
            &nbsp;·&nbsp;
            Skor: <span style="color:{score_color};font-weight:800;">{signal.score:+.0f}</span>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:11px;color:#8b90a0;font-weight:700;
                      text-transform:uppercase;letter-spacing:0.12em;">Stop-Loss</div>
          <div style="font-size:22px;font-weight:900;color:#ff796c;">
            ₺{signal.stop_loss:.2f}
          </div>
          <div style="font-size:11px;color:#8b90a0;font-weight:700;
                      text-transform:uppercase;letter-spacing:0.12em;margin-top:10px;">
            Hedef
          </div>
          <div style="font-size:22px;font-weight:900;color:#48ddbc;">
            ₺{signal.target_price:.2f}
          </div>
        </div>
      </div>

      <div style="margin-top:14px;">
        <div class="score-bar-wrap">
          <div class="{bar_class}" style="width:{bar_width}%;"></div>
        </div>
      </div>

      <div style="margin-top:12px;">
        {reason_chips}
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def render_indicator_grid(snapshot, signal):
    rsi = snapshot.get("rsi", 50)
    macd = snapshot.get("macd_cross", "NONE")
    sma = snapshot.get("sma_cross", "NONE")
    bb = snapshot.get("bb_position", "MIDDLE")
    vol = snapshot.get("volume_ratio", 1.0)
    atr = snapshot.get("atr", 0)

    def rsi_badge(v):
        v = float(v)
        if v < 30:
            return "oversold", "Aşırı Satım"
        if v > 70:
            return "overbought", "Aşırı Alım"
        return "neutral", "Nötr"

    def cross_badge(v):
        if "BULL" in str(v) or "GOLDEN" in str(v):
            return "bullish", "Yükseliş"
        if "BEAR" in str(v) or "DEATH" in str(v):
            return "bearish", "Düşüş"
        return "neutral", "Nötr"

    def bb_badge(v):
        if "BELOW" in str(v):
            return "oversold", "Alt Band"
        if "ABOVE" in str(v):
            return "overbought", "Üst Band"
        return "neutral", "Orta"

    def vol_badge(v):
        v = float(v)
        if v >= 2.0:
            return "bullish", "Yüksek"
        if v < 0.8:
            return "bearish", "Düşük"
        return "neutral", "Normal"

    rsi_cls, rsi_lbl = rsi_badge(rsi)
    macd_cls, macd_lbl = cross_badge(macd)
    sma_cls, sma_lbl = cross_badge(sma)
    bb_cls, bb_lbl = bb_badge(bb)
    vol_cls, vol_lbl = vol_badge(vol)

    rows_html = f"""
    <div class="indicator-row">
      <span class="indicator-name">RSI (14)</span>
      <span class="indicator-value">{float(rsi):.1f}</span>
      <span class="indicator-badge {rsi_cls}">{rsi_lbl}</span>
    </div>
    <div class="indicator-row">
      <span class="indicator-name">MACD Cross</span>
      <span class="indicator-value">{macd}</span>
      <span class="indicator-badge {macd_cls}">{macd_lbl}</span>
    </div>
    <div class="indicator-row">
      <span class="indicator-name">SMA Cross</span>
      <span class="indicator-value">{sma}</span>
      <span class="indicator-badge {sma_cls}">{sma_lbl}</span>
    </div>
    <div class="indicator-row">
      <span class="indicator-name">Bollinger</span>
      <span class="indicator-value">{bb}</span>
      <span class="indicator-badge {bb_cls}">{bb_lbl}</span>
    </div>
    <div class="indicator-row">
      <span class="indicator-name">Hacim Oranı</span>
      <span class="indicator-value">{float(vol):.2f}x</span>
      <span class="indicator-badge {vol_cls}">{vol_lbl}</span>
    </div>
    <div class="indicator-row">
      <span class="indicator-name">ATR</span>
      <span class="indicator-value">₺{float(atr):.2f}</span>
      <span class="indicator-badge neutral">Volatilite</span>
    </div>
    """

    st.markdown(f"<div class='indicator-table'>{rows_html}</div>", unsafe_allow_html=True)


def render_mini_info_cards(df, snapshot):
    try:
        high_52w = float(df["high"].tail(252).max())
        low_52w = float(df["low"].tail(252).min())
        avg_vol = int(df["volume"].tail(20).mean())
        last_close = float(snapshot.get("close", 0))
        dist_from_high = ((last_close - high_52w) / high_52w * 100) if high_52w else 0
        dist_from_low = ((last_close - low_52w) / low_52w * 100) if low_52w else 0
    except Exception:
        high_52w = low_52w = avg_vol = 0
        dist_from_high = dist_from_low = 0

    support = snapshot.get("support", 0)
    resistance = snapshot.get("resistance", 0)

    cards = [
        ("52H Yüksek", f"₺{high_52w:.2f}", f"{dist_from_high:+.1f}% şimdiden"),
        ("52H Düşük", f"₺{low_52w:.2f}", f"{dist_from_low:+.1f}% şimdiden"),
        ("Ort. Hacim", f"{avg_vol:,}", "Son 20 gün"),
        ("Destek", f"₺{float(support):.2f}", "Yakın destek"),
        ("Direnç", f"₺{float(resistance):.2f}", "Yakın direnç"),
        ("ATR", f"₺{float(snapshot.get('atr', 0)):.2f}", "Günlük volatilite"),
    ]

    items_html = "".join(
        f"""
    <div class="mini-info-card">
      <div class="mini-info-label">{label}</div>
      <div class="mini-info-value">{value}</div>
      <div class="mini-info-sub">{sub}</div>
    </div>
    """
        for label, value, sub in cards
    )

    st.markdown(f"<div class='mini-info-grid'>{items_html}</div>", unsafe_allow_html=True)


def plot_candlestick(df, ticker):
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df.index,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing_line_color="#48ddbc",
                decreasing_line_color="#ff796c",
                name=ticker,
            )
        ]
    )
    if "sma_20" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["sma_20"], mode="lines", name="SMA 20", line=dict(color="#adc6ff", width=2)))
    if "ema_50" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ema_50"], mode="lines", name="EMA 50", line=dict(color="#ffb4aa", width=2)))
    fig.update_layout(template="plotly_dark", height=440, margin=dict(l=10, r=10, t=20, b=10), xaxis_rangeslider_visible=False)
    return fig


def plot_volume(df):
    colors = ["#48ddbc" if df["close"].iloc[i] >= df["open"].iloc[i] else "#ff796c" for i in range(len(df))]
    fig = go.Figure(data=[go.Bar(x=df.index, y=df["volume"], marker_color=colors)])
    fig.update_layout(template="plotly_dark", height=180, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    return fig


def plot_rsi(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], mode="lines", line=dict(color="#48ddbc", width=2)))
    fig.add_hrect(y0=0, y1=30, fillcolor="green", opacity=0.08, line_width=0)
    fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.08, line_width=0)
    fig.add_hline(y=50, line_dash="dash", line_color="#8b90a0")
    fig.update_layout(template="plotly_dark", height=180, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(range=[0, 100]), showlegend=False)
    return fig


def filter_signals(base_signals, all_data):
    filtered = [s for s in base_signals if s.score >= st.session_state.min_score_filter]
    if st.session_state.rsi_min_filter <= 0 and st.session_state.rsi_max_filter >= 100 and st.session_state.vol_ratio_filter <= 0:
        return filtered
    ti = TechnicalIndicators()
    result = []
    for signal in filtered:
        df = all_data.get(signal.ticker)
        if df is None:
            continue
        try:
            last = ti.add_all(df.copy()).iloc[-1]
            rsi = last.get("rsi", 50)
            volume_ratio = last.get("volume_ratio", 1.0)
            if st.session_state.rsi_min_filter <= rsi <= st.session_state.rsi_max_filter and volume_ratio >= st.session_state.vol_ratio_filter:
                result.append(signal)
        except Exception:
            pass
    return result


def render_signal_card(signal, df_data=None):
    name = config.TICKER_NAMES.get(signal.ticker, signal.ticker)
    chip_class = "buy" if signal.score >= 10 else "sell"
    with st.container(border=True):
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.markdown(f"### {signal.ticker.replace('.IS', '')}")
            st.caption(name)
            st.markdown(f"<span class='signal-chip {chip_class}'>{signal.signal_type.value}</span>", unsafe_allow_html=True)
            st.write(f"**Skor:** {signal.score:+.0f}")
            st.write(f"**Fiyat:** ₺{signal.price:.2f}")
            st.write(f"**Stop:** ₺{signal.stop_loss:.2f}")
            st.write(f"**Hedef:** ₺{signal.target_price:.2f}")
            st.write(f"**Guven:** {signal.confidence}")
        with c2:
            if df_data is not None:
                st.plotly_chart(plot_candlestick(TechnicalIndicators().add_all(df_data.tail(90).copy()), signal.ticker), use_container_width=True, key=f"card_{signal.ticker}")
        if signal.reasons:
            st.markdown("**Nedenler**")
            for reason in signal.reasons[:5]:
                st.write(f"- {reason}")


def render_signal_card_v2(signal, df_data=None):
    name = config.TICKER_NAMES.get(signal.ticker, signal.ticker)
    ticker_short = signal.ticker.replace(".IS", "")

    if signal.score >= 10:
        card_class = "signal-card-buy"
        bar_class = "score-bar-fill"
        chip_class = "buy"
    elif signal.score < 0:
        card_class = "signal-card-sell"
        bar_class = "score-bar-fill negative"
        chip_class = "sell"
    else:
        card_class = "signal-card-neutral"
        bar_class = "score-bar-fill"
        chip_class = "buy"

    bar_width = int((signal.score + 100) / 2)
    reason_chips = "".join(
        f"<span class='reason-chip'>{r[:60]}</span>"
        for r in signal.reasons[:6]
    )
    price_color = "#48ddbc" if signal.score >= 0 else "#ff796c"

    left_html = f"""
    <div class='{card_class}'>
      <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
        <div>
          <div style='font-size:26px;font-weight:900;letter-spacing:-0.03em;color:#dfe2eb;'>{ticker_short}</div>
          <div style='font-size:12px;color:#8b90a0;margin-top:2px;'>{name}</div>
        </div>
        <span class='signal-chip {chip_class}'>{signal.signal_type.value}</span>
      </div>

      <div style='margin-top:14px;display:flex;gap:20px;'>
        <div>
          <div style='font-size:11px;color:#8b90a0;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;'>Fiyat</div>
          <div style='font-size:20px;font-weight:800;color:{price_color};'>TL{signal.price:.2f}</div>
        </div>
        <div>
          <div style='font-size:11px;color:#8b90a0;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;'>Stop</div>
          <div style='font-size:20px;font-weight:800;color:#dfe2eb;'>TL{signal.stop_loss:.2f}</div>
        </div>
        <div>
          <div style='font-size:11px;color:#8b90a0;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;'>Hedef</div>
          <div style='font-size:20px;font-weight:800;color:#dfe2eb;'>TL{signal.target_price:.2f}</div>
        </div>
        <div>
          <div style='font-size:11px;color:#8b90a0;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;'>Guven</div>
          <div style='font-size:20px;font-weight:800;color:#dfe2eb;'>{signal.confidence}</div>
        </div>
      </div>

      <div style='margin-top:12px;'>
        <div style='display:flex;justify-content:space-between;font-size:11px;color:#8b90a0;margin-bottom:4px;'>
          <span>Skor</span><span style='font-weight:800;color:#dfe2eb;'>{signal.score:+.0f}</span>
        </div>
        <div class='score-bar-wrap'>
          <div class='{bar_class}' style='width:{bar_width}%;'></div>
        </div>
      </div>

      <div style='margin-top:12px;'>
        {reason_chips}
      </div>
    </div>
    """

    if df_data is not None:
        col_left, col_right = st.columns([1.4, 1])
        with col_left:
            st.markdown(left_html, unsafe_allow_html=True)
        with col_right:
            try:
                df_chart = TechnicalIndicators().add_all(df_data.tail(60).copy())
                spark = go.Figure()
                spark.add_trace(go.Scatter(
                    x=df_chart.index,
                    y=df_chart["close"],
                    mode="lines",
                    line=dict(
                        color="#48ddbc" if signal.score >= 0 else "#ff796c",
                        width=2
                    ),
                    fill="tozeroy",
                    fillcolor="rgba(72,221,188,0.05)" if signal.score >= 0 else "rgba(255,121,108,0.05)"
                ))
                spark.update_layout(
                    template="plotly_dark",
                    height=180,
                    margin=dict(l=0, r=0, t=8, b=0),
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False),
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)"
                )
                st.plotly_chart(spark, use_container_width=True, key=f"spark_{signal.ticker}_{id(signal)}")
            except Exception:
                st.markdown(left_html, unsafe_allow_html=True)
    else:
        st.markdown(left_html, unsafe_allow_html=True)


def render_top_shell(signals, summary):
    strong_count = len([s for s in signals if s.score >= 40])
    positive_count = len([s for s in signals if s.score >= 10])
    analyzed = summary.get("total_analyzed", len(config.WATCHLIST))
    avg_rsi = summary.get("avg_rsi", 50)
    scan_time = st.session_state.last_scan_time.strftime("%H:%M") if st.session_state.last_scan_time else datetime.now().strftime("%H:%M")
    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="eyebrow">Bist Bot Terminal</div>
            <div class="hero-title">Modern trading cockpit for BIST signals</div>
            <div class="hero-copy">Gercek zamanli tarama, teknik sinyal akisi, tekil hisse analizi ve bot ayarlari tek bir mobil uyumlu uygulama kabugunda toplandi.</div>
            <div style="margin-top:18px;">
                <span class="pill-stat">Canli tarama: {analyzed} hisse</span>
                <span class="pill-stat">Guclu sinyal: {strong_count}</span>
                <span class="pill-stat">Pozitif set: {positive_count}</span>
                <span class="pill-stat">Ortalama RSI: {avg_rsi:.1f}</span>
                <span class="pill-stat">Son guncelleme: {scan_time}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_navigation():
    items = [
        ("dashboard", "Dashboard", "◫"),
        ("signals", "Signals", "◌"),
        ("analysis", "Analysis", "◭"),
        ("settings", "Settings", "◎"),
    ]
    links = []
    for view, label, icon in items:
        active = "active" if st.session_state.current_view == view else ""
        links.append(f'<a class="{active}" href="?view={view}"><span class="bottom-nav-icon">{icon}</span><span>{label}</span></a>')
    st.markdown(f'<div class="bottom-nav">{"".join(links)}</div>', unsafe_allow_html=True)


def metric_card(title, value, subtitle=""):
    st.markdown(f"<div class='metric-shell'><div class='metric-kicker'>{title}</div><div class='metric-value'>{value}</div><div class='metric-sub'>{subtitle}</div></div>", unsafe_allow_html=True)


def render_dashboard(signals, summary):
    hero_col, index_col = st.columns([2.4, 1], gap="large")
    with hero_col:
        render_portfolio_hero(signals, summary)
    with index_col:
        render_index_cards()

    strong = [s for s in signals if s.score >= 40]
    buy = [s for s in signals if 10 <= s.score < 40]
    sell = [s for s in signals if s.score < 0]
    pos_rate = round(len(strong + buy) / len(signals) * 100) if signals else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Guclu Al", str(len(strong)), "Yuksek guvenli")
    with c2:
        metric_card("Al Akisi", str(len(buy)), "Pozitif momentum")
    with c3:
        metric_card("Sat Baskisi", str(len(sell)), "Dikkat gereken")
    with c4:
        metric_card("Pozitif Oran", f"{pos_rate}%", "Pozitif sinyal orani")

    left_col, right_col = st.columns([1.6, 1], gap="large")

    with left_col:
        st.markdown("<div class='section-title'>Portfolio Pulse</div>", unsafe_allow_html=True)
        top = strong[:5] if strong else sorted(signals, key=lambda x: x.score, reverse=True)[:5]
        if not top:
            st.info("Dashboard verisi icin once tarama yapin.")
        else:
            rows = []
            for signal in top:
                name = config.TICKER_NAMES.get(signal.ticker, signal.ticker)
                chip = "buy" if signal.score >= 10 else "sell"
                rows.append(
                    f"<div class='list-row'>"
                    f"<div style='display:flex;justify-content:space-between;gap:12px;align-items:center;'>"
                    f"<div><div style='font-size:20px;font-weight:800;color:#dfe2eb;'>{signal.ticker.replace('.IS','')}</div>"
                    f"<div style='font-size:12px;color:#8b90a0;'>{name}</div></div>"
                    f"<div style='text-align:right;'>"
                    f"<span class='signal-chip {chip}'>{signal.signal_type.value}</span>"
                    f"<div style='margin-top:6px;font-size:12px;color:#c1c6d7;'>"
                    f"₺{signal.price:.2f} &nbsp;·&nbsp; Skor {signal.score:+.0f}"
                    f"</div></div></div></div>"
                )
            st.markdown(f"<div class='surface-shell'>{''.join(rows)}</div>", unsafe_allow_html=True)

    with right_col:
        st.markdown("<div class='section-title'>Live Insights</div>", unsafe_allow_html=True)
        render_live_insights(signals)


def render_signals(signals, all_data):
    st.markdown("<div class='section-title'>Active Signals</div>", unsafe_allow_html=True)
    strong_tab, buy_tab, sell_tab = st.tabs(["Strong Buy", "Buy", "Sell / Neutral"])
    with strong_tab:
        strong = [s for s in signals if s.score >= 40]
        if strong:
            for signal in strong:
                render_signal_card_v2(signal, all_data.get(signal.ticker))
        else:
            st.info("Guclu alim sinyali yok.")
    with buy_tab:
        buy = [s for s in signals if 10 <= s.score < 40]
        if buy:
            for signal in buy:
                render_signal_card_v2(signal, all_data.get(signal.ticker))
        else:
            st.info("Alim sinyali yok.")
    with sell_tab:
        sell = [s for s in signals if s.score < 10]
        if sell:
            for signal in sell:
                render_signal_card_v2(signal, all_data.get(signal.ticker))
        else:
            st.info("Satis sinyali yok.")


def render_analysis(all_data):
    st.markdown(
        "<div class='section-title'>Technical Analysis</div>",
        unsafe_allow_html=True,
    )

    ticker_list = list(all_data.keys()) if all_data else config.WATCHLIST
    c1, c2, c3 = st.columns([1.4, 1, 1])
    with c1:
        current_idx = ticker_list.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in ticker_list else 0
        st.session_state.selected_ticker = st.selectbox(
            "Hisse",
            ticker_list,
            index=current_idx,
            format_func=lambda x: f"{config.TICKER_NAMES.get(x, x)} ({x.replace('.IS', '')})",
        )
    with c2:
        period_options = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
        labels = {"1mo": "1 Ay", "3mo": "3 Ay", "6mo": "6 Ay", "1y": "1 Yıl", "2y": "2 Yıl", "5y": "5 Yıl"}
        st.session_state.analysis_period = st.selectbox(
            "Periyot",
            period_options,
            index=period_options.index(st.session_state.analysis_period),
            format_func=lambda x: labels[x],
        )
    with c3:
        if st.button("Haberleri getir", use_container_width=True):
            with st.spinner("Haberler alınıyor..."):
                st.session_state[f"news_{st.session_state.selected_ticker}"] = fetch_stock_news(st.session_state.selected_ticker)

    df = st.session_state.data_fetcher.fetch_single(
        st.session_state.selected_ticker,
        period=st.session_state.analysis_period,
    )
    if df is None:
        st.error("Analiz verisi yüklenemedi.")
        return

    df = TechnicalIndicators().add_all(df)
    snapshot = TechnicalIndicators().get_snapshot(df)
    signal = st.session_state.engine.analyze(
        st.session_state.selected_ticker,
        df,
    )

    render_stock_identity(st.session_state.selected_ticker, snapshot)

    chart_col, side_col = st.columns([2.2, 1], gap="large")
    with chart_col:
        st.plotly_chart(
            plot_candlestick(df, st.session_state.selected_ticker),
            use_container_width=True,
        )
        st.plotly_chart(plot_volume(df), use_container_width=True)
    with side_col:
        render_verdict_card(signal)
        st.plotly_chart(plot_rsi(df), use_container_width=True)
        render_indicator_grid(snapshot, signal)

    info_col, news_col = st.columns([1.2, 1], gap="large")
    with info_col:
        st.markdown(
            "<div style='font-size:14px;font-weight:800;color:#8b90a0;text-transform:uppercase;letter-spacing:0.14em;margin-bottom:10px;'>Mini Bilgi</div>",
            unsafe_allow_html=True,
        )
        render_mini_info_cards(df, snapshot)
    with news_col:
        with st.container(border=True):
            st.subheader("Haber akışı")
            news = st.session_state.get(f"news_{st.session_state.selected_ticker}", [])
            if news:
                for item in news[:6]:
                    title = item.get("title", "Haber")
                    url = item.get("url", "")
                    source = item.get("source", "Kaynak")
                    if url:
                        st.markdown(f"- [{source}: {title}]({url})")
                    else:
                        st.write(f"- {source}: {title}")
            else:
                st.caption("Haberleri getir butonuyla seçili hisse için bağlamsal akış açabilirsiniz.")


def render_settings(signals):
    st.markdown(
        "<div class='section-title'>Bot Settings</div>",
        unsafe_allow_html=True
    )

    col_left, col_right = st.columns([1.5, 1], gap="large")

    with col_left:
        st.markdown("""
        <div class='settings-group'>
          <div class='settings-group-title'>Tarama ve Filtreler</div>
        </div>
        """, unsafe_allow_html=True)
        with st.container(border=False):
            st.session_state.auto_refresh = st.toggle(
                "Otomatik yenile", value=st.session_state.auto_refresh
            )
            st.session_state.refresh_interval = st.select_slider(
                "Tarama aralığı (dk)",
                options=[1, 3, 5, 10, 15],
                value=st.session_state.refresh_interval
            )
            st.session_state.min_score_filter = st.slider(
                "Minimum skor", -100, 100,
                st.session_state.min_score_filter
            )
            r1, r2 = st.columns(2)
            with r1:
                st.session_state.rsi_min_filter = st.slider(
                    "RSI min", 0, 100, st.session_state.rsi_min_filter
                )
            with r2:
                st.session_state.rsi_max_filter = st.slider(
                    "RSI max", 0, 100, st.session_state.rsi_max_filter
                )
            st.session_state.vol_ratio_filter = st.slider(
                "Min hacim oranı", 0.0, 5.0,
                st.session_state.vol_ratio_filter, 0.1
            )

        st.divider()

        st.markdown("""
        <div class='settings-group'>
          <div class='settings-group-title'>İndikatör Parametreleri</div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("RSI Ayarları", expanded=False):
            st.session_state.ind_rsi_period = st.slider(
                "RSI Periyot", 5, 30,
                st.session_state.ind_rsi_period
            )
            rc1, rc2 = st.columns(2)
            with rc1:
                st.session_state.ind_rsi_oversold = st.slider(
                    "Aşırı Satım", 10, 40,
                    st.session_state.ind_rsi_oversold
                )
            with rc2:
                st.session_state.ind_rsi_overbought = st.slider(
                    "Aşırı Alım", 60, 90,
                    st.session_state.ind_rsi_overbought
                )

        with st.expander("MACD Ayarları", expanded=False):
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                st.session_state.ind_macd_fast = st.slider(
                    "Hızlı", 5, 20,
                    st.session_state.ind_macd_fast
                )
            with mc2:
                st.session_state.ind_macd_slow = st.slider(
                    "Yavaş", 20, 50,
                    st.session_state.ind_macd_slow
                )
            with mc3:
                st.session_state.ind_macd_signal = st.slider(
                    "Sinyal", 5, 20,
                    st.session_state.ind_macd_signal
                )

        with st.expander("SMA / EMA Ayarları", expanded=False):
            sc1, sc2 = st.columns(2)
            with sc1:
                st.session_state.ind_sma_fast = st.slider(
                    "SMA Hızlı", 5, 30,
                    st.session_state.ind_sma_fast
                )
                st.session_state.ind_ema_fast = st.slider(
                    "EMA Hızlı", 5, 30,
                    st.session_state.ind_ema_fast
                )
            with sc2:
                st.session_state.ind_sma_slow = st.slider(
                    "SMA Yavaş", 20, 100,
                    st.session_state.ind_sma_slow
                )
                st.session_state.ind_ema_slow = st.slider(
                    "EMA Yavaş", 20, 100,
                    st.session_state.ind_ema_slow
                )

        with st.expander("Bollinger & ADX", expanded=False):
            bc1, bc2 = st.columns(2)
            with bc1:
                st.session_state.ind_bb_period = st.slider(
                    "BB Periyot", 10, 30,
                    st.session_state.ind_bb_period
                )
            with bc2:
                st.session_state.ind_bb_std = st.slider(
                    "BB Std", 1.0, 3.0,
                    st.session_state.ind_bb_std, 0.1
                )
            st.session_state.ind_adx_threshold = st.slider(
                "ADX Eşiği", 10, 40,
                st.session_state.ind_adx_threshold
            )

        st.divider()

        st.markdown("""
        <div class='settings-group'>
          <div class='settings-group-title'>Telegram Bildirimleri</div>
        </div>
        """, unsafe_allow_html=True)

        st.session_state.tg_token_input = st.text_input(
            "Bot Token",
            value=st.session_state.tg_token_input,
            type="password",
            placeholder="123456789:AAxxxxxx..."
        )
        st.session_state.tg_chat_input = st.text_input(
            "Chat ID",
            value=st.session_state.tg_chat_input,
            placeholder="-100123456789"
        )
        st.session_state.notify_min_score = st.slider(
            "Bildirim min skor", 0, 100,
            st.session_state.notify_min_score
        )
        tg_ready = bool(
            st.session_state.tg_token_input and
            st.session_state.tg_chat_input
        )
        st.session_state.notify_telegram = st.toggle(
            "Telegram bildirimi",
            value=st.session_state.notify_telegram,
            disabled=not tg_ready
        )
        if not tg_ready:
            st.caption("Token ve Chat ID girilmeden bildirim aktif edilemez.")

    with col_right:
        st.markdown("""
        <div class='settings-group'>
          <div class='settings-group-title'>Canlı Durum</div>
        </div>
        """, unsafe_allow_html=True)

        next_scan = "Kapalı"
        if st.session_state.auto_refresh and st.session_state.last_scan_time:
            elapsed = (
                datetime.now() - st.session_state.last_scan_time
            ).total_seconds()
            remaining = max(
                0, st.session_state.refresh_interval * 60 - elapsed
            )
            next_scan = f"{remaining:.0f}s"

        tg_status = (
            "✅ Hazır" if tg_ready else "⚠️ Eksik"
        )

        with st.container(border=True):
            st.metric("Watchlist",      len(config.WATCHLIST))
            st.metric("Aktif sinyal",  len(signals))
            st.metric("Telegram",      tg_status)
            st.metric("Sonraki tarama", next_scan)

        st.markdown("""
        <div class='settings-group' style='margin-top:14px;'>
          <div class='settings-group-title'>Risk Yönetimi</div>
        </div>
        """, unsafe_allow_html=True)

        strong_count = len([s for s in signals if s.score >= 40])
        sell_count   = len([s for s in signals if s.score < 0])
        total        = len(signals)
        pos_rate     = round(strong_count / total * 100) if total > 0 else 0
        avg_score    = round(
            sum(s.score for s in signals) / total
        ) if total > 0 else 0

        risk_cards = [
            ("Güçlü Sinyal Oranı", f"{pos_rate}%",
             f"{strong_count} / {total} güçlü"),
            ("Ortalama Skor",      f"{avg_score:+d}",
             "Tüm hisseler ortalaması"),
            ("Sat Baskısı",        str(sell_count),
             "Negatif skorlu hisse"),
            ("Min Skor Filtresi",
             str(st.session_state.min_score_filter),
             "Aktif filtre eşiği"),
        ]

        for title, value, sub in risk_cards:
            st.markdown(f"""
            <div class="risk-card">
              <div class="risk-card-title">{title}</div>
              <div class="risk-card-value">{value}</div>
              <div class="risk-card-sub">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

        changed = []
        param_map = [
            ("RSI Periyot",   "ind_rsi_period",    config.RSI_PERIOD),
            ("RSI Satım",     "ind_rsi_oversold",  config.RSI_OVERSOLD),
            ("RSI Alım",       "ind_rsi_overbought",config.RSI_OVERBOUGHT),
            ("SMA Hızlı",     "ind_sma_fast",      config.SMA_FAST),
            ("SMA Yavaş",     "ind_sma_slow",      config.SMA_SLOW),
            ("EMA Hızlı",     "ind_ema_fast",      config.EMA_FAST),
            ("EMA Yavaş",     "ind_ema_slow",      config.EMA_SLOW),
            ("MACD Hızlı",    "ind_macd_fast",    config.MACD_FAST),
            ("MACD Yavaş",    "ind_macd_slow",    config.MACD_SLOW),
            ("MACD Sinyal",   "ind_macd_signal",  config.MACD_SIGNAL),
            ("BB Periyot",    "ind_bb_period",    config.BOLLINGER_PERIOD),
            ("BB Std",        "ind_bb_std",       float(config.BOLLINGER_STD)),
            ("ADX Eşiği",     "ind_adx_threshold", config.ADX_THRESHOLD),
        ]
        for label, key, default in param_map:
            current = st.session_state.get(key, default)
            if current != default:
                changed.append((label, default, current))

        if changed:
            rows_html = "".join(f"""
            <div class="param-row">
              <span class="param-name">{label}</span>
              <span class="param-value">
                {default} → {current}
                <span class="param-changed">değişti</span>
              </span>
            </div>
            """ for label, default, current in changed)

            st.markdown(f"""
            <div style='margin-top:12px;'>
              <div style='font-size:11px;font-weight:800;letter-spacing:0.16em;
                          text-transform:uppercase;color:#8b90a0;
                          margin-bottom:8px;'>
                Değiştirilen Parametreler
              </div>
              <div class='indicator-table'>{rows_html}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("""
        <div class='deploy-btn-wrap'>
          <div class='deploy-title'>Deploy Configuration</div>
          <div class='deploy-sub'>
            Değiştirilen parametreler bir sonraki taramada aktif olur.
            Şu an runtime override — config.py yazılmaz.
          </div>
        </div>
        """, unsafe_allow_html=True)

        deploy_col1, deploy_col2 = st.columns(2)
        with deploy_col1:
            if st.button(
                "⚡ Taramayı Yenile",
                use_container_width=True,
                type="primary"
            ):
                config.RSI_PERIOD       = st.session_state.ind_rsi_period
                config.RSI_OVERSOLD     = st.session_state.ind_rsi_oversold
                config.RSI_OVERBOUGHT   = st.session_state.ind_rsi_overbought
                config.SMA_FAST         = st.session_state.ind_sma_fast
                config.SMA_SLOW         = st.session_state.ind_sma_slow
                config.EMA_FAST         = st.session_state.ind_ema_fast
                config.EMA_SLOW         = st.session_state.ind_ema_slow
                config.MACD_FAST        = st.session_state.ind_macd_fast
                config.MACD_SLOW        = st.session_state.ind_macd_slow
                config.MACD_SIGNAL      = st.session_state.ind_macd_signal
                config.BOLLINGER_PERIOD = st.session_state.ind_bb_period
                config.BOLLINGER_STD    = st.session_state.ind_bb_std
                config.ADX_THRESHOLD    = st.session_state.ind_adx_threshold
                if st.session_state.tg_token_input:
                    config.TELEGRAM_BOT_TOKEN = st.session_state.tg_token_input
                if st.session_state.tg_chat_input:
                    config.TELEGRAM_CHAT_ID = st.session_state.tg_chat_input
                run_scan()
                st.session_state.deploy_confirmed = True
                st.rerun()

        with deploy_col2:
            if st.button(
                "↺ Varsayılana Dön",
                use_container_width=True
            ):
                keys_to_reset = [
                    "ind_rsi_period","ind_rsi_oversold","ind_rsi_overbought",
                    "ind_sma_fast","ind_sma_slow","ind_ema_fast","ind_ema_slow",
                    "ind_macd_fast","ind_macd_slow","ind_macd_signal",
                    "ind_bb_period","ind_bb_std","ind_adx_threshold",
                    "tg_token_input","tg_chat_input","deploy_confirmed",
                ]
                for k in keys_to_reset:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()

        if st.session_state.get("deploy_confirmed"):
            st.success(
                "✅ Parametreler uygulandı ve tarama yenilendi.",
                icon="✅"
            )


bootstrap_state()
inject_styles()
ensure_initial_data()

signals = filter_signals(st.session_state.get("signals", []), st.session_state.get("all_data", {}))
all_data = st.session_state.get("all_data", {})
market_summary = get_market_summary(signals, all_data)

if st.session_state.auto_refresh and st.session_state.last_scan_time:
    elapsed = (datetime.now() - st.session_state.last_scan_time).total_seconds()
    if elapsed >= st.session_state.refresh_interval * 60:
        run_scan()
        st.rerun()

render_top_shell(signals, market_summary)

if not signals:
    st.warning("Sinyal bulunamadi. Tarama tekrarlandiginda ekran otomatik dolacak.")
else:
    if st.session_state.current_view == "dashboard":
        render_dashboard(signals, market_summary)
    elif st.session_state.current_view == "signals":
        render_signals(signals, all_data)
    elif st.session_state.current_view == "analysis":
        render_analysis(all_data)
    else:
        render_settings(signals)

st.markdown(f"<div class='footer-note'>BIST Bot modern terminal · Son guncelleme {datetime.now().strftime('%d.%m.%Y %H:%M')}</div>", unsafe_allow_html=True)
render_navigation()
