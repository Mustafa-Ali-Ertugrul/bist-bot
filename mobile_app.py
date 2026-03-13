import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

import config
from data_fetcher import BISTDataFetcher
from indicators import TechnicalIndicators
from strategy import StrategyEngine, SignalType
from notifier import TelegramNotifier


st.set_page_config(
    page_title="BIST Sinyal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp { background: #0d1117; }
    [data-testid="stSidebar"] { display: none; }
    .stButton > button {
        width: 100%;
        padding: 15px;
        font-size: 16px;
        border-radius: 10px;
    }
    h1 { font-size: 24px !important; }
    h2 { font-size: 18px !important; }
    h3 { font-size: 16px !important; }
    div[data-testid="stMetric"] {
        background: #161b22;
        padding: 10px;
        border-radius: 8px;
    }
    .signal-buy { background: #1a3d1a; padding: 10px; border-radius: 8px; margin: 5px 0; }
    .signal-sell { background: #3d1a1a; padding: 10px; border-radius: 8px; margin: 5px 0; }
    .signal-neutral { background: #1a1a1a; padding: 10px; border-radius: 8px; margin: 5px 0; }
</style>
""", unsafe_allow_html=True)


def check_signals(ticker, df):
    if df is None or len(df) < 30:
        return None, []
    
    ti = TechnicalIndicators()
    df = ti.add_all(df)
    last = df.iloc[-1]
    
    conditions = []
    
    rsi = last.get("rsi")
    if rsi and rsi < 45:
        conditions.append(f"RSI: {rsi:.0f}")
    
    vol_ratio = last.get("volume_ratio", 1.0)
    if vol_ratio and vol_ratio > 1.0:
        conditions.append(f"Hacim: {vol_ratio:.1f}x")
    
    macd_cross = last.get("macd_cross")
    if macd_cross == "BULLISH":
        conditions.append("MACD: BULLISH")
    
    sma_cross = last.get("sma_cross")
    if sma_cross == "GOLDEN_CROSS":
        conditions.append("SMA: GOLDEN_CROSS")
    
    count = len(conditions)
    
    if count >= 3:
        return "AL", conditions
    elif count == 2:
        return "SAT", conditions
    else:
        return None, conditions


def send_notification(ticker, signal_type, conditions):
    name = config.TICKER_NAMES.get(ticker, ticker)
    emoji = "🚀" if signal_type == "AL" else "🔴"
    message = f"{emoji} {signal_type}: {name}\n" + "\n".join(conditions)
    notifier = TelegramNotifier()
    notifier.send_message(message)


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
