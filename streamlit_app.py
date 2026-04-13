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
            section[data-testid="stSidebar"] {display:none !important;}
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
                bottom: 14px;
                transform: translateX(-50%);
                width: min(760px, calc(100vw - 20px));
                background: rgba(16,20,26,0.92);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 22px;
                backdrop-filter: blur(20px);
                box-shadow: 0 20px 50px rgba(0,0,0,0.35);
                padding: 10px;
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                z-index: 9999;
            }
            .bottom-nav a {
                text-decoration: none;
                color: #9aa4b2;
                border-radius: 16px;
                padding: 10px 6px;
                text-align: center;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.14em;
                text-transform: uppercase;
                transition: all 0.18s ease;
                border: 1px solid transparent;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 6px;
            }
            .bottom-nav a.active {
                background: rgba(72,221,188,0.12);
                color: #48ddbc;
                border-color: rgba(72,221,188,0.18);
            }
            .bottom-nav-icon {
                font-size: 18px;
                line-height: 1;
                letter-spacing: normal;
            }
            @media (max-width: 768px) {
                .block-container {padding-left:0.8rem;padding-right:0.8rem;}
                .hero-shell {padding:20px;border-radius:20px;}
                .hero-title {font-size:32px;}
                .bottom-nav {bottom: 10px; width: calc(100vw - 16px); border-radius: 18px;}
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
    strong = [s for s in signals if s.score >= 40]
    buy = [s for s in signals if 10 <= s.score < 40]
    sell = [s for s in signals if s.score < 10]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Strong buy", str(len(strong)), "Yuksek guvenli sinyaller")
    with c2:
        metric_card("Buy flow", str(len(buy)), "Pozitif momentum")
    with c3:
        metric_card("Sell pressure", str(len(sell)), "Korunma gerekenler")
    with c4:
        metric_card("Avg volume", f"{summary.get('avg_vol_ratio', 1.0):.2f}x", "Normal hacme gore")

    left, right = st.columns([1.6, 1], gap="large")
    with left:
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
                    f"<div class='list-row'><div style='display:flex;justify-content:space-between;gap:12px;align-items:start;'><div><div style='font-size:20px;font-weight:800;color:#dfe2eb;'>{signal.ticker.replace('.IS','')}</div><div style='font-size:12px;color:#8b90a0;'>{name}</div></div><div style='text-align:right;'><span class='signal-chip {chip}'>{signal.signal_type.value}</span><div style='margin-top:8px;font-size:12px;color:#c1c6d7;'>Skor {signal.score:+.0f}</div></div></div></div>"
                )
            st.markdown(f"<div class='surface-shell'>{''.join(rows)}</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='section-title'>Market Breadth</div>", unsafe_allow_html=True)
        dist = summary.get("sector_dist", {})
        with st.container(border=True):
            st.metric("Asiri satim", dist.get("Asırı Satım", 0))
            st.metric("Notr", dist.get("Nötr", 0))
            st.metric("Asiri alim", dist.get("Asırı Alım", 0))


def render_signals(signals, all_data):
    st.markdown("<div class='section-title'>Active Signals</div>", unsafe_allow_html=True)
    strong_tab, buy_tab, sell_tab = st.tabs(["Strong Buy", "Buy", "Sell / Neutral"])
    with strong_tab:
        strong = [s for s in signals if s.score >= 40]
        if strong:
            for signal in strong:
                render_signal_card(signal, all_data.get(signal.ticker))
        else:
            st.info("Guclu alim sinyali yok.")
    with buy_tab:
        buy = [s for s in signals if 10 <= s.score < 40]
        if buy:
            for signal in buy:
                render_signal_card(signal, all_data.get(signal.ticker))
        else:
            st.info("Alim sinyali yok.")
    with sell_tab:
        sell = [s for s in signals if s.score < 10]
        if sell:
            for signal in sell:
                render_signal_card(signal, all_data.get(signal.ticker))
        else:
            st.info("Satis sinyali yok.")


def render_analysis(all_data):
    st.markdown("<div class='section-title'>Technical Analysis</div>", unsafe_allow_html=True)
    ticker_list = list(all_data.keys()) if all_data else config.WATCHLIST
    c1, c2, c3 = st.columns([1.4, 1, 1])
    with c1:
        current_idx = ticker_list.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in ticker_list else 0
        st.session_state.selected_ticker = st.selectbox("Hisse", ticker_list, index=current_idx, format_func=lambda x: f"{config.TICKER_NAMES.get(x, x)} ({x.replace('.IS', '')})")
    with c2:
        period_options = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
        st.session_state.analysis_period = st.selectbox("Periyot", period_options, index=period_options.index(st.session_state.analysis_period), format_func=lambda x: {"1mo": "1 Ay", "3mo": "3 Ay", "6mo": "6 Ay", "1y": "1 Yil", "2y": "2 Yil", "5y": "5 Yil"}[x])
    with c3:
        if st.button("Haberleri getir", use_container_width=True):
            with st.spinner("Haberler aliniyor..."):
                st.session_state[f"news_{st.session_state.selected_ticker}"] = fetch_stock_news(st.session_state.selected_ticker)

    df = st.session_state.data_fetcher.fetch_single(st.session_state.selected_ticker, period=st.session_state.analysis_period)
    if df is None:
        st.error("Analiz verisi yuklenemedi.")
        return
    df = TechnicalIndicators().add_all(df)
    snapshot = TechnicalIndicators().get_snapshot(df)
    signal = st.session_state.engine.analyze(st.session_state.selected_ticker, df)

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        metric_card("Price", f"₺{snapshot['close']}", f"Gunluk {snapshot['change_pct']}%")
    with m2:
        metric_card("RSI", f"{snapshot['rsi']:.0f}", snapshot.get("rsi_zone", "Notr"))
    with m3:
        metric_card("Volume", f"{snapshot['volume_ratio']:.1f}x", "Hacim hizi")
    with m4:
        metric_card("ATR", f"₺{snapshot['atr']:.2f}", "Volatilite")
    with m5:
        metric_card("Signal", signal.signal_type.value if signal else "Yok", f"Skor {signal.score:+.0f}" if signal else "Bekle")

    chart_col, side_col = st.columns([2.2, 1], gap="large")
    with chart_col:
        st.plotly_chart(plot_candlestick(df, st.session_state.selected_ticker), use_container_width=True)
    with side_col:
        st.plotly_chart(plot_rsi(df), use_container_width=True)
        st.plotly_chart(plot_volume(df), use_container_width=True)

    info_col, news_col = st.columns([1.3, 1], gap="large")
    with info_col:
        with st.container(border=True):
            st.subheader("Teknik ozet")
            st.write(f"**SMA Cross:** {snapshot['sma_cross']}")
            st.write(f"**MACD Cross:** {snapshot['macd_cross']}")
            st.write(f"**BB Position:** {snapshot['bb_position']}")
            st.write(f"**Destek:** ₺{snapshot['support']:.2f}")
            st.write(f"**Direnc:** ₺{snapshot['resistance']:.2f}")
            if signal:
                st.write(f"**Stop-Loss:** ₺{signal.stop_loss:.2f}")
                st.write(f"**Hedef:** ₺{signal.target_price:.2f}")
                st.markdown("**Nedenler**")
                for reason in signal.reasons[:5]:
                    st.write(f"- {reason}")
    with news_col:
        with st.container(border=True):
            st.subheader("Haber akisi")
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
                st.caption("Haberleri getir butonuyla secili hisse icin baglamsal akis acabilirsiniz.")


def render_settings(signals):
    st.markdown("<div class='section-title'>Bot Settings</div>", unsafe_allow_html=True)
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Tarama ve filtreler")
            st.session_state.auto_refresh = st.toggle("Otomatik yenile", value=st.session_state.auto_refresh)
            st.session_state.refresh_interval = st.select_slider("Tarama araligi", options=[1, 3, 5, 10, 15], value=st.session_state.refresh_interval)
            st.session_state.min_score_filter = st.slider("Minimum skor", -100, 100, st.session_state.min_score_filter)
            r1, r2 = st.columns(2)
            with r1:
                st.session_state.rsi_min_filter = st.slider("RSI min", 0, 100, st.session_state.rsi_min_filter)
            with r2:
                st.session_state.rsi_max_filter = st.slider("RSI max", 0, 100, st.session_state.rsi_max_filter)
            st.session_state.vol_ratio_filter = st.slider("Minimum hacim orani", 0.0, 5.0, st.session_state.vol_ratio_filter, 0.1)
        with st.container(border=True):
            st.subheader("Bildirimler")
            st.session_state.notify_min_score = st.slider("Bildirim min skor", 0, 100, st.session_state.notify_min_score)
            st.session_state.notify_telegram = st.toggle("Telegram bildirimi", value=st.session_state.notify_telegram, disabled=not bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID))
    with right:
        with st.container(border=True):
            st.subheader("Canli durum")
            st.metric("Watchlist", len(config.WATCHLIST))
            st.metric("Aktif sinyal", len(signals))
            st.metric("Telegram", "Hazir" if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID else "Yok")
            next_scan = "Kapali"
            if st.session_state.auto_refresh and st.session_state.last_scan_time:
                elapsed = (datetime.now() - st.session_state.last_scan_time).total_seconds()
                next_scan = f"{max(0, st.session_state.refresh_interval * 60 - elapsed):.0f}s"
            st.metric("Sonraki tarama", next_scan)
        if st.button("Taramayi yenile", use_container_width=True, type="primary"):
            run_scan()
            st.rerun()


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
