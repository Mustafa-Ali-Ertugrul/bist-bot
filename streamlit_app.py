import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

import config
from data_fetcher import BISTDataFetcher
from indicators import TechnicalIndicators
from strategy import StrategyEngine, SignalType

st.set_page_config(
    page_title="BIST Bot",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="expanded"
)

if "data_fetcher" not in st.session_state:
    st.session_state.data_fetcher = BISTDataFetcher()
if "engine" not in st.session_state:
    st.session_state.engine = StrategyEngine()

st.markdown("""
<style>
    .stApp {
        background: #0d1117;
    }
    /* Mobil için büyük butonlar */
    .stButton > button {
        width: 100%;
        padding: 20px;
        font-size: 18px;
        border-radius: 15px;
    }
    /* Mobil metin boyutları */
    .stMarkdown {
        font-size: 16px;
    }
    h1 {
        font-size: 28px !important;
    }
    h2 {
        font-size: 22px !important;
    }
    h3 {
        font-size: 18px !important;
    }
    /* Metric kartları mobilde büyük */
    div[data-testid="stMetric"] {
        background: #161b22;
        padding: 15px;
        border-radius: 10px;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 14px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 20px;
    }
    /* Expander mobilde tam genişlik */
    .streamlit-expanderHeader {
        font-size: 16px;
        padding: 15px;
    }
    /* Tablo mobilde kaydırılabilir */
    .dataframe {
        font-size: 12px;
    }
    /* Sidebar mobilde açık */
    section[data-testid="stSidebar"] {
        width: 100% !important;
    }
    /* Metrik değerleri */
    p, li {
        font-size: 15px;
    }
</style>
""", unsafe_allow_html=True)


def get_signal_emoji(signal_type):
    emojis = {
        SignalType.STRONG_BUY: "🚀💰",
        SignalType.BUY: "🟢",
        SignalType.WEAK_BUY: "🟡",
        SignalType.HOLD: "⚪",
        SignalType.WEAK_SELL: "🟠",
        SignalType.SELL: "🔴",
        SignalType.STRONG_SELL: "🚨",
    }
    return emojis.get(signal_type, "📊")


def get_signal_color(signal_type):
    if signal_type in [SignalType.STRONG_BUY, SignalType.BUY]:
        return "green"
    elif signal_type in [SignalType.STRONG_SELL, SignalType.SELL]:
        return "red"
    return "gray"


def run_scan():
    try:
        fetcher = st.session_state.data_fetcher
        engine = st.session_state.engine
        
        with st.spinner("Veriler cekiliyor..."):
            fetcher.clear_cache()
            all_data = fetcher.fetch_all()
        
        with st.spinner("Analiz yapiliyor..."):
            signals = engine.scan_all(all_data)
        
        return signals, all_data
    except Exception as e:
        st.error(f"Hata: {str(e)}")
        return [], {}


def plot_candlestick(df, ticker):
    fig = go.Figure(data=[go.Candlestick(
        x=df.index,
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name=ticker
    )])
    
    if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
        last = df.iloc[-1]
        fig.add_trace(go.Scatter(
            x=df.index, y=df['bb_upper'],
            mode='lines', name='BB Upper',
            line=dict(color='red', width=1, dash='dash')
        ))
        fig.add_trace(go.Scatter(
            x=df.index, y=df['bb_lower'],
            mode='lines', name='BB Lower',
            line=dict(color='green', width=1, dash='dash')
        ))
    
    if 'sma_5' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['sma_5'],
            mode='lines', name='SMA 5',
            line=dict(color='yellow', width=1)
        ))
    
    if 'sma_20' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['sma_20'],
            mode='lines', name='SMA 20',
            line=dict(color='blue', width=1)
        ))
    
    fig.update_layout(
        template="plotly_dark",
        height=400,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False
    )
    return fig


def plot_volume(df):
    colors = ['green' if df['close'].iloc[i] >= df['open'].iloc[i] else 'red' 
              for i in range(len(df))]
    
    fig = go.Figure(data=[go.Bar(
        x=df.index,
        y=df['volume'],
        marker_color=colors,
        name='Volume'
    )])
    
    if 'volume_sma_20' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['volume_sma_20'],
            mode='lines', name='Vol SMA 20',
            line=dict(color='orange', width=2)
        ))
    
    fig.update_layout(
        template="plotly_dark",
        height=150,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False
    )
    return fig


def plot_rsi(df):
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df.index, y=df['rsi'],
        mode='lines', name='RSI',
        line=dict(color='purple', width=2)
    ))
    
    fig.add_hrect(y0=0, y1=30, fillcolor="green", opacity=0.1, line_width=0)
    fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.1, line_width=0)
    fig.add_hline(y=50, line_dash="dash", line_color="gray")
    
    fig.update_layout(
        template="plotly_dark",
        height=150,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis=dict(range=[0, 100]),
        showlegend=False
    )
    return fig


st.title("🤖 BIST Trading Bot")

with st.sidebar:
    st.header("⚙️ Ayarlar")
    
    selected_ticker = st.selectbox(
        "Hisse Seç",
        config.WATCHLIST,
        format_func=lambda x: f"{config.TICKER_NAMES.get(x, x)} ({x.replace('.IS', '')})"
    )
    
    st.divider()
    
    if st.button("🔄 Taramayı Yenile", type="primary"):
        st.session_state.signals, st.session_state.all_data = run_scan()
    
    if "signals" not in st.session_state:
        st.session_state.signals = []
        st.session_state.all_data = {}
    

if not st.session_state.signals:
    st.info("👆 'Taramayı Yenile' butonuna basarak başlayın!")
    st.markdown("""
    ### 📖 Kullanım
    
    1. **Taramayı Yenile** butonuna basın
    2. Tüm hisseler analiz edilir
    3. Sinyaller skoruna göre sıralanır
    4. Hisse seçip detaylı grafikleri inceleyin
    """)

else:
    signals = st.session_state.signals
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Taranan", len(st.session_state.all_data))
    with col2:
        buys = len([s for s in signals if s.score > 0])
        st.metric("Alım Sinyali", buys, delta_color="normal")
    with col3:
        sells = len([s for s in signals if s.score < 0])
        st.metric("Satış Sinyali", sells, delta_color="inverse")
    with col4:
        st.metric("Son Tarama", datetime.now().strftime("%H:%M"))
    
    st.divider()
    
    tab1, tab2 = st.tabs(["Sinyaller", f"{selected_ticker} Detay"])
    
    with tab1:
        st.subheader("Alim Sinyalleri")
        
        buy_signals = [s for s in signals if s.score > 0]
        if buy_signals:
            for s in buy_signals:
                name = config.TICKER_NAMES.get(s.ticker, s.ticker)
                risk = (s.price - s.stop_loss) / s.price * 100
                reward = (s.target_price - s.price) / s.price * 100
                rr = reward / risk if risk > 0 else 0
                
                # Verileri al
                df_data = st.session_state.all_data.get(s.ticker)
                if df_data is not None and len(df_data) >= 2:
                    prev_price = df_data['close'].iloc[-2]
                    day_change = (s.price - prev_price) / prev_price * 100
                    change_color = "green" if day_change > 0 else "red"
                    change_str = f":{change_color}[{day_change:+.1f}%]"
                else:
                    day_change = 0
                    change_str = "0%"
                
                with st.expander(f"{get_signal_emoji(s.signal_type)} **{name}** ({s.ticker.replace('.IS', '')}) | Skor: {s.score:+.0f} | {change_str}"):
                    # Mini grafik - Alim Seviyeleri
                    fig_levels = go.Figure()
                    
                    # Zarar bölgesi (kirmizi)
                    fig_levels.add_vrect(
                        x0=s.stop_loss, x1=s.price,
                        fillcolor="red", opacity=0.15, line_width=0,
                        annotation_text="ZARAR", annotation_position="bottom left"
                    )
                    
                    # Kazanç bölgesi (yesil)
                    fig_levels.add_vrect(
                        x0=s.price, x1=s.target_price,
                        fillcolor="green", opacity=0.15, line_width=0,
                        annotation_text="KAZANC", annotation_position="top left"
                    )
                    
                    # Fiyat çizgileri
                    fig_levels.add_hline(y=0, line_dash="solid", line_color="white", line_width=2, annotation_text=f"Giris: ₺{s.price:.2f}", annotation_position="top")
                    fig_levels.add_hline(y=0, line_dash="dash", line_color="red", line_width=2, annotation_text=f"Stop: ₺{s.stop_loss:.2f}", annotation_position="bottom")
                    fig_levels.add_hline(y=0, line_dash="dash", line_color="green", line_width=2, annotation_text=f"Hedef: ₺{s.target_price:.2f}", annotation_position="top")
                    
                    fig_levels.update_layout(
                        height=120,
                        margin=dict(l=10, r=10, t=30, b=30),
                        xaxis=dict(
                            range=[s.stop_loss * 0.95, s.target_price * 1.05],
                            showgrid=False
                        ),
                        yaxis=dict(showticklabels=False, showgrid=False),
                        template="plotly_dark",
                        showlegend=False
                    )
                    st.plotly_chart(fig_levels, use_container_width=True)
                    
                    # Ana metrikler
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Giris", f"₺{s.price:.2f}", delta=f"{day_change:+.1f}%")
                    with col2:
                        st.metric("Stop", f"₺{s.stop_loss:.2f}", delta=f"-{risk:.1f}%", delta_color="inverse")
                    with col3:
                        st.metric("Hedef", f"₺{s.target_price:.2f}", delta=f"+{reward:.1f}%", delta_color="normal")
                    with col4:
                        st.metric("R/R", f"1:{rr:.1f}")
                    
                    # RSI
                    if df_data is not None:
                        ti = TechnicalIndicators()
                        df_indicators = ti.add_rsi(df_data.copy())
                        rsi = df_indicators['rsi'].iloc[-1]
                        rsi_color = "green" if rsi < 30 else "red" if rsi > 70 else "yellow"
                        st.markdown(f"**RSI:** :{rsi_color}[{rsi:.0f}]")
                    
                    # Nedenler
                    st.markdown("**Nedenler:**")
                    for r in s.reasons[:5]:
                        st.write(f"• {r}")
        else:
            st.info("Alim sinyali yok")
        
        st.subheader("Satis Sinyalleri")
        
        sell_signals = [s for s in signals if s.score < 0]
        if sell_signals:
            for s in sell_signals:
                name = config.TICKER_NAMES.get(s.ticker, s.ticker)
                
                df_data = st.session_state.all_data.get(s.ticker)
                if df_data is not None and len(df_data) >= 2:
                    prev_price = df_data['close'].iloc[-2]
                    day_change = (s.price - prev_price) / prev_price * 100
                    change_color = "green" if day_change > 0 else "red"
                    change_str = f":{change_color}[{day_change:+.1f}%]"
                else:
                    day_change = 0
                    change_str = "0%"
                
                with st.expander(f"{get_signal_emoji(s.signal_type)} **{name}** ({s.ticker.replace('.IS', '')}) | Skor: {s.score:+.0f} | {change_str}"):
                    # Mini grafik - Satis Seviyeleri
                    fig_levels = go.Figure()
                    
                    # Yukarı hareket bölgesi (kirmizi - satista kar)
                    fig_levels.add_vrect(
                        x0=s.price, x1=s.target_price,
                        fillcolor="red", opacity=0.15, line_width=0,
                        annotation_text="KISA POZ. KAZANC", annotation_position="top left"
                    )
                    
                    fig_levels.add_hline(y=0, line_dash="solid", line_color="white", line_width=2, annotation_text=f"Giris: ₺{s.price:.2f}", annotation_position="top")
                    fig_levels.add_hline(y=0, line_dash="dash", line_color="green", line_width=2, annotation_text=f"Stop: ₺{s.target_price:.2f}", annotation_position="bottom")
                    
                    fig_levels.update_layout(
                        height=120,
                        margin=dict(l=10, r=10, t=30, b=30),
                        xaxis=dict(
                            range=[s.price * 0.95, s.target_price * 1.05],
                            showgrid=False
                        ),
                        yaxis=dict(showticklabels=False, showgrid=False),
                        template="plotly_dark",
                        showlegend=False
                    )
                    st.plotly_chart(fig_levels, use_container_width=True)
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Fiyat", f"₺{s.price:.2f}", delta=f"{day_change:+.1f}%")
                    with col2:
                        st.metric("Hedef", f"₺{s.target_price:.2f}")
                    with col3:
                        st.metric("Güven", s.confidence)
                    
                    if df_data is not None:
                        ti = TechnicalIndicators()
                        df_indicators = ti.add_rsi(df_data.copy())
                        rsi = df_indicators['rsi'].iloc[-1]
                        rsi_color = "green" if rsi < 30 else "red" if rsi > 70 else "yellow"
                        st.markdown(f"**RSI:** :{rsi_color}[{rsi:.0f}]")
                    
                    st.markdown("**Nedenler:**")
                    for r in s.reasons[:5]:
                        st.write(f"• {r}")
        else:
            st.info("Satis sinyali yok")
    
    with tab2:
        fetcher = st.session_state.data_fetcher
        
        with st.spinner("Veri yükleniyor..."):
            df = fetcher.fetch_single(selected_ticker, period="6mo")
        
        if df is not None:
            ti = TechnicalIndicators()
            df = ti.add_all(df)
            snapshot = ti.get_snapshot(df)
            signal = st.session_state.engine.analyze(selected_ticker, df)
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Fiyat", f"₺{snapshot['close']}", delta=f"{snapshot['change_pct']}%")
            with col2:
                st.metric("RSI", f"{snapshot['rsi']:.0f}")
            with col3:
                st.metric("Hacim", f"{snapshot['volume']/1_000_000:.1f}M")
            with col4:
                st.metric("ATR", f"₺{snapshot['atr']:.2f}")
            with col5:
                st.metric("Destek", f"₺{snapshot['support']:.2f}")
            
            st.divider()
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.plotly_chart(plot_candlestick(df, selected_ticker), use_container_width=True)
            with col2:
                st.plotly_chart(plot_rsi(df), use_container_width=True)
                st.plotly_chart(plot_volume(df), use_container_width=True)
            
            st.divider()
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 📉 Teknik Göstergeler")
                st.write(f"**RSI:** {snapshot['rsi']:.1f} ({snapshot['rsi_zone']})")
                st.write(f"**SMA Cross:** {snapshot['sma_cross']}")
                st.write(f"**MACD Cross:** {snapshot['macd_cross']}")
                st.write(f"**BB Position:** {snapshot['bb_position']}")
                st.write(f"**Hacim Oranı:** {snapshot['volume_ratio']}x")
            
            with col2:
                st.markdown("### 🎯 Alım/Satım")
                if signal:
                    color = get_signal_color(signal.signal_type)
                    st.markdown(f":{color}[**{signal.signal_type.value}**]")
                    st.write(f"**Skor:** {signal.score:+.0f}/100")
                    st.write(f"**Stop-Loss:** ₺{signal.stop_loss:.2f}")
                    st.write(f"**Hedef:** ₺{signal.target_price:.2f}")
                    
                    st.markdown("**Nedenler:**")
                    for r in signal.reasons[:5]:
                        st.write(f"• {r}")
            
            st.divider()
            
            with st.expander("📊 Fiyar Verileri"):
                st.dataframe(
                    df[['open', 'high', 'low', 'close', 'volume']].tail(30),
                    use_container_width=True
                )
        
        else:
            st.error("Veri yüklenemedi!")

st.markdown("---")
st.caption(f"🤖 BIST Bot v1.0 | Son güncelleme: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
