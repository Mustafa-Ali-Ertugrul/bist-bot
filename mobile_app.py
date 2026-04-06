import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

import config
from data_fetcher import BISTDataFetcher
from indicators import TechnicalIndicators
from strategy import StrategyEngine, SignalType
from streamlit_utils import check_signals, send_signal_notification


st.set_page_config(
    page_title="BIST Sinyal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { 
        background: linear-gradient(135deg, #0a0e1a 0%, #111827 50%, #0f172a 100%);
    }
    [data-testid="stSidebar"] { display: none; }
    
    /* Modern Buttons */
    .stButton > button {
        width: 100%;
        padding: 16px;
        font-size: 16px;
        border-radius: 12px;
        font-weight: 600;
        border: none;
        background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
        color: white;
        box-shadow: 0 4px 15px rgba(30, 64, 175, 0.3);
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 25px rgba(30, 64, 175, 0.45);
    }
    
    /* Typography */
    h1 { 
        font-size: 28px !important;
        font-weight: 800 !important;
        background: linear-gradient(135deg, #1e3a8a, #1e40af, #2563eb);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    h2 { 
        font-size: 20px !important;
        font-weight: 700 !important;
        color: #f1f5f9;
    }
    h3 { 
        font-size: 16px !important;
        font-weight: 600 !important;
        color: #e2e8f0;
    }
    
    /* Glassmorphism Metrics */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        padding: 14px;
    }
    
    /* Signal Cards */
    .signal-buy { 
        background: rgba(16, 185, 129, 0.08);
        border: 1px solid rgba(16, 185, 129, 0.2);
        padding: 14px;
        border-radius: 12px;
        margin: 8px 0;
    }
    .signal-sell { 
        background: rgba(239, 68, 68, 0.08);
        border: 1px solid rgba(239, 68, 68, 0.2);
        padding: 14px;
        border-radius: 12px;
        margin: 8px 0;
    }
    .signal-neutral { 
        background: rgba(148, 163, 184, 0.06);
        border: 1px solid rgba(148, 163, 184, 0.15);
        padding: 14px;
        border-radius: 12px;
        margin: 8px 0;
    }
    
    /* Expander Modern */
    .streamlit-expanderHeader {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
    }
    
    /* Selectbox */
    .stSelectbox > div > div {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def get_all_data():
    fetcher = BISTDataFetcher()
    return fetcher.fetch_all()


if "data" not in st.session_state:
    st.session_state.data = get_all_data()

data = st.session_state.data

st.title("📈 BIST Sinyal")

col1, col2 = st.columns([2, 1])
with col1:
    st.write(f"**Taranan:** {len(data)} hisse")
with col2:
    if st.button("🔄 Yenile"):
        st.session_state.data = get_all_data()
        st.rerun()

st.divider()

signals = []
for ticker, df in data.items():
    signal_type, conditions = check_signals(ticker, df)
    if signal_type:
        signals.append({
            "ticker": ticker,
            "signal": signal_type,
            "conditions": conditions,
            "price": df["close"].iloc[-1] if df is not None else 0
        })

al_sinyalleri = [s for s in signals if s["signal"] == "AL"]
sat_sinyalleri = [s for s in signals if s["signal"] == "SAT"]

st.subheader(f"🚀 Al Sinyalleri ({len(al_sinyalleri)})")
if al_sinyalleri:
    for s in al_sinyalleri:
        name = config.TICKER_NAMES.get(s["ticker"], s["ticker"])
        with st.expander(f"🚀 {name} - ₺{s['price']:.2f}"):
            for c in s["conditions"]:
                st.write(f"✅ {c}")
else:
    st.write("Henüz al sinyali yok")

st.divider()

st.subheader(f"🔴 Sat Sinyalleri ({len(sat_sinyalleri)})")
if sat_sinyalleri:
    for s in sat_sinyalleri:
        name = config.TICKER_NAMES.get(s["ticker"], s["ticker"])
        with st.expander(f"🔴 {name} - ₺{s['price']:.2f}"):
            for c in s["conditions"]:
                st.write(f"❌ {c}")
else:
    st.write("Henüz sat sinyali yok")

st.divider()

st.subheader("📊 Tüm Hisseler")
ticker_list = list(data.keys())
selected = st.selectbox(
    "Hisse seç",
    ticker_list,
    format_func=lambda x: f"{config.TICKER_NAMES.get(x, x)} ({x.replace('.IS', '')})"
)

if selected:
    df = data[selected]
    ti = TechnicalIndicators()
    df = ti.add_all(df)
    last = df.iloc[-1]
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Fiyat", f"₺{last['close']:.2f}")
    with col2:
        rsi = last.get("rsi", 0)
        st.metric("RSI", f"{rsi:.0f}")
    
    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df['open'], high=df['high'],
        low=df['low'], close=df['close']
    )])
    fig.update_layout(template="plotly_dark", height=300)
    st.plotly_chart(fig, use_container_width=True)
