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
    page_title="BIST Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto"
)

st.markdown("""
<style>
    section[data-testid="stSidebar"] {
        width: 200px !important;
    }
</style>
""", unsafe_allow_html=True)

if "data_fetcher" not in st.session_state:
    st.session_state.data_fetcher = BISTDataFetcher()
if "engine" not in st.session_state:
    st.session_state.engine = StrategyEngine()

if "signals" not in st.session_state or len(st.session_state.get("signals", [])) == 0:
    try:
        fetcher = st.session_state.data_fetcher
        engine = st.session_state.engine
        fetcher.clear_cache()
        all_data = fetcher.fetch_all()
        signals = engine.scan_all(all_data)
        
        for ticker, df in all_data.items():
            signal_type, conditions = check_signals(ticker, df)
            if signal_type:
                send_signal_notification(ticker, signal_type, conditions)
        
        st.session_state.signals = signals
        st.session_state.all_data = all_data
        st.rerun()
    except Exception as e:
        st.error(f"Tarama hatası: {e}")

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


def render_signal_card(s, is_sell=False):
    name = config.TICKER_NAMES.get(s.ticker, s.ticker)
    risk = (s.price - s.stop_loss) / s.price * 100
    reward = (s.target_price - s.price) / s.price * 100
    rr = reward / risk if risk > 0 else 0
    
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
        if df_data is not None:
            df_chart = df_data.tail(30).copy()
            df_chart = df_chart.reset_index()
            df_chart = df_chart.dropna()
            
            fig = go.Figure()
            
            fig.add_trace(go.Candlestick(
                x=df_chart.index,
                open=df_chart['open'],
                high=df_chart['high'],
                low=df_chart['low'],
                close=df_chart['close'],
                name='Fiyat',
                increasing_line_color='#00CC96',
                decreasing_line_color='#EF553B'
            ))
            
            if not is_sell:
                fig.add_hline(y=s.price, line_dash="solid", line_color="#3399FF", line_width=2)
                fig.add_hline(y=s.stop_loss, line_dash="dash", line_color="#EF553B", line_width=2)
                fig.add_hline(y=s.target_price, line_dash="dash", line_color="#00CC96", line_width=2)
                fig.add_hrect(y0=s.stop_loss, y1=s.price, fillcolor="#EF553B", opacity=0.15, line_width=0, layer="below")
                fig.add_hrect(y0=s.price, y1=s.target_price, fillcolor="#00CC96", opacity=0.15, line_width=0, layer="below")
                fig.add_annotation(x=0, y=s.price, xref="paper", yref="y", text=f"G: {s.price:.2f}", showarrow=False, xanchor="left", bgcolor="#3399FF", font=dict(color="white"))
                fig.add_annotation(x=0, y=s.stop_loss, xref="paper", yref="y", text=f"S: {s.stop_loss:.2f}", showarrow=False, xanchor="left", bgcolor="#EF553B", font=dict(color="white"))
                fig.add_annotation(x=0, y=s.target_price, xref="paper", yref="y", text=f"H: {s.target_price:.2f}", showarrow=False, xanchor="left", bgcolor="#00CC96", font=dict(color="white"))
            else:
                fig.add_hline(y=s.price, line_dash="solid", line_color="#FF9900", line_width=2)
                fig.add_hline(y=s.target_price, line_dash="dash", line_color="#EF553B", line_width=2)
                fig.add_hrect(y0=s.price, y1=s.target_price, fillcolor="#EF553B", opacity=0.15, line_width=0, layer="below")
                fig.add_annotation(x=0, y=s.price, xref="paper", yref="y", text=f"G: {s.price:.2f}", showarrow=False, xanchor="left", bgcolor="#FF9900", font=dict(color="white"))
                fig.add_annotation(x=0, y=s.target_price, xref="paper", yref="y", text=f"H: {s.target_price:.2f}", showarrow=False, xanchor="left", bgcolor="#EF553B", font=dict(color="white"))
            
            fig.update_layout(height=280, template="plotly_dark", margin=dict(l=60, r=20, t=40, b=40), xaxis_rangeslider_visible=False, showlegend=False, plot_bgcolor="#0d1117", paper_bgcolor="#0d1117")
            st.plotly_chart(fig, use_container_width=True, key=f"chart_{s.ticker}_{s.signal_type.name}")
        
        if not is_sell:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Giris", f"₺{s.price:.2f}", delta=f"{day_change:+.1f}%")
            with col2:
                st.metric("Stop", f"₺{s.stop_loss:.2f}", delta=f"-{risk:.1f}%", delta_color="inverse")
            with col3:
                st.metric("Hedef", f"₺{s.target_price:.2f}", delta=f"+{reward:.1f}%", delta_color="normal")
            with col4:
                st.metric("R/R", f"1:{rr:.1f}")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Fiyat", f"₺{s.price:.2f}", delta=f"{day_change:+.1f}%")
            with col2:
                st.metric("Hedef", f"₺{s.target_price:.2f}")
            with col3:
                st.metric("Güven", s.confidence)
        
        if df_data is not None:
            ti = TechnicalIndicators()
            df_indicators = ti.add_all(df_data.copy())
            last = df_indicators.iloc[-1]
            
            rsi = last['rsi']
            rsi_color = "green" if rsi < 30 else "red" if rsi > 70 else "white"
            rsi_durum = "Asiri Satim" if rsi < 30 else "Asiri Alim" if rsi > 70 else "Nötr"
            
            stoch_k = last.get('stoch_k', 50)
            stoch_d = last.get('stoch_d', 50)
            stoch_color = "green" if stoch_k < 20 else "red" if stoch_k > 80 else "white"
            
            vol_ratio = last['volume_ratio']
            vol_color = "green" if vol_ratio > 1.5 else "red" if vol_ratio < 0.8 else "white"
            
            macd_cross = last['macd_cross']
            macd_color = "green" if macd_cross == "BULLISH" else "red" if macd_cross == "BEARISH" else "white"
            
            sma_cross = last['sma_cross']
            sma_color = "green" if sma_cross == "GOLDEN_CROSS" else "red" if sma_cross == "DEATH_CROSS" else "white"
            
            ema_cross = last.get('ema_cross', 'NONE')
            ema_color = "green" if ema_cross == "BULLISH" else "red" if ema_cross == "BEARISH" else "white"
            
            adx = last.get('adx', 0)
            adx_str = "Güçlü" if adx > 25 else "Zayıf"
            
            cci = last.get('cci', 0)
            cci_color = "green" if cci < -100 else "red" if cci > 100 else "white"
            
            obv_trend = last.get('obv_trend', 'FLAT')
            obv_color = "green" if obv_trend == "UP" else "red" if obv_trend == "DOWN" else "white"
            
            rsi_div = last.get('rsi_divergence', 'NONE')
            macd_div = last.get('macd_divergence', 'NONE')
            
            st.markdown("### Gostergeler")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f"**RSI:** :{rsi_color}[{rsi:.0f}] - {rsi_durum}")
                st.markdown(f"**Stoch:** :{stoch_color}[K:{stoch_k:.0f}/D:{stoch_d:.0f}]")
            with col2:
                st.markdown(f"**Hacim:** :{vol_color}[{vol_ratio:.1f}x]")
                st.markdown(f"**OBV:** :{obv_color}[{obv_trend}]")
            with col3:
                st.markdown(f"**MACD:** :{macd_color}[{macd_cross}]")
                st.markdown(f"**CCI:** :{cci_color}[{cci:.0f}]")
            with col4:
                st.markdown(f"**SMA:** :{sma_color}[{sma_cross}]")
                st.markdown(f"**ADX:** [{adx:.0f}] {adx_str}")
            
            if rsi_div != 'NONE' or macd_div != 'NONE' or ema_cross != 'NONE':
                st.markdown("### Ek Sinyaller")
                col1, col2, col3 = st.columns(3)
                with col1:
                    div_color = "green" if rsi_div == "BULLISH" else "red" if rsi_div == "BEARISH" else "white"
                    st.markdown(f"**RSI Div:** :{div_color}[{rsi_div}]")
                with col2:
                    div_color = "green" if macd_div == "BULLISH" else "red" if macd_div == "BEARISH" else "white"
                    st.markdown(f"**MACD Div:** :{div_color}[{macd_div}]")
                with col3:
                    em_color = "green" if ema_cross == "BULLISH" else "red" if ema_cross == "BEARISH" else "white"
                    st.markdown(f"**EMA:** :{em_color}[{ema_cross}]")
        
        st.markdown("**Nedenler:**")
        for r in s.reasons[:5]:
            st.write(f"• {r}")


st.title("🤖 BIST Trading Bot")

with st.sidebar:
    st.header("⚙️ Ayarlar")
    
    selected_ticker = st.selectbox(
        "Hisse Seç",
        config.WATCHLIST,
        format_func=lambda x: f"{config.TICKER_NAMES.get(x, x)} ({x.replace('.IS', '')})"
    )
    
    st.divider()
    
    if "signals" not in st.session_state or len(st.session_state.get("signals", [])) == 0:
        st.session_state.signals, st.session_state.all_data = run_scan()
        st.rerun()
    
    if st.button("🔄 Taramayı Yenile", type="primary"):
        st.session_state.signals, st.session_state.all_data = run_scan()
    

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
    
    total = len(st.session_state.all_data)
    buys = len([s for s in signals if s.score > 0])
    sells = len([s for s in signals if s.score < 0])
    neutral = total - buys - sells
    buy_pct = (buys / total * 100) if total > 0 else 0
    sell_pct = (sells / total * 100) if total > 0 else 0
    neutral_pct = (neutral / total * 100) if total > 0 else 0
    
    from strategy import SignalType
    strong_buy_count = len([s for s in signals if s.score >= 40])
    buy_count = len([s for s in signals if 10 <= s.score < 40])
    sell_count = len([s for s in signals if s.score < 10])
    
    total_score = sum(s.score for s in signals)
    max_possible = total * 100
    sentiment = (total_score / max_possible * 100) if max_possible > 0 else 0
    sentiment_clamped = max(-100, min(100, sentiment))
    
    if sentiment_clamped > 20:
        sentiment_label = "ALIM AGIRLIKLI"
        sentiment_color = "#00CC96"
        sentiment_emoji = "🟢"
    elif sentiment_clamped < -20:
        sentiment_label = "SATIS AGIRLIKLI"
        sentiment_color = "#EF553B"
        sentiment_emoji = "🔴"
    else:
        sentiment_label = "NOTR"
        sentiment_color = "#8b949e"
        sentiment_emoji = "⚪"
    
    st.markdown(f"""
    <style>
        .signal-card {{
            background: #161b22;
            border-radius: 16px;
            padding: 20px;
            margin: 8px 0;
            border: 1px solid #30363d;
            text-align: center;
        }}
        .gauge-container {{
            position: relative;
            width: 180px;
            height: 180px;
            margin: 0 auto 12px;
        }}
        .gauge-ring {{
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: conic-gradient(
                #00CC96 0deg {buy_pct * 3.6}deg,
                #EF553B {buy_pct * 3.6}deg {buy_pct * 3.6 + sell_pct * 3.6}deg,
                #ffffff {buy_pct * 3.6 + sell_pct * 3.6}deg 360deg
            );
            mask: radial-gradient(transparent 55%, black 56%);
            -webkit-mask: radial-gradient(transparent 55%, black 56%);
        }}
        .gauge-center {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
        }}
        .gauge-sentiment {{
            font-size: 14px;
            font-weight: bold;
            color: {sentiment_color};
            letter-spacing: 1px;
        }}
        .gauge-score {{
            font-size: 28px;
            font-weight: bold;
            color: #fff;
            margin-top: 2px;
        }}
        .signal-stats {{
            display: flex;
            justify-content: space-around;
            margin-top: 12px;
        }}
        .stat-item {{
            text-align: center;
        }}
        .stat-value {{
            font-size: 22px;
            font-weight: bold;
        }}
        .stat-label {{
            font-size: 12px;
            color: #8b949e;
            margin-top: 2px;
        }}
        .scan-time {{
            text-align: center;
            color: #8b949e;
            font-size: 13px;
            margin-top: 12px;
            padding-top: 10px;
            border-top: 1px solid #21262d;
        }}
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div class="signal-card">
        <div class="gauge-container">
            <div class="gauge-ring"></div>
            <div class="gauge-center">
                <div class="gauge-sentiment">{sentiment_emoji} {sentiment_label}</div>
                <div class="gauge-score">{sentiment_clamped:+.0f}</div>
            </div>
        </div>
        <div class="signal-stats">
            <div class="stat-item">
                <div class="stat-value" style="color:#00CC96;">{buys}</div>
                <div class="stat-label">🟢 Alım</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" style="color:#ffffff;">{neutral}</div>
                <div class="stat-label">⚪ Nötr</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" style="color:#EF553B;">{sells}</div>
                <div class="stat-label">🔴 Satış</div>
            </div>
        </div>
        <div class="scan-time">🕐 Son Tarama: {datetime.now().strftime("%H:%M")} | Taranan: {total} hisse</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    tab1, tab2, tab3 = st.tabs(["Sinyaller", f"{selected_ticker} Detay", "Tüm Hisseler"])
    
    with tab1:
        sub_strong, sub_buy, sub_sell = st.tabs(["💰 Güçlü Alım", "🟢 Alım", "🔴 Satış"])
        
        with sub_strong:
            strong_buy_signals = [s for s in signals if s.score >= 40]
            if strong_buy_signals:
                for s in strong_buy_signals:
                    render_signal_card(s)
            else:
                st.info("Güçlü alım sinyali yok")
        
        with sub_buy:
            buy_signals = [s for s in signals if 10 <= s.score < 40]
            if buy_signals:
                for s in buy_signals:
                    render_signal_card(s)
            else:
                st.info("Alım sinyali yok")
        
        with sub_sell:
            sell_signals = [s for s in signals if s.score < 10]
            if sell_signals:
                for s in sell_signals:
                    render_signal_card(s, is_sell=True)
            else:
                st.info("Satış sinyali yok")
    
    with tab3:
        st.subheader("Tüm Hisseler Detay")
        
        if not st.session_state.all_data:
            st.warning("Önce tarama yapın!")
        else:
            ticker_list = list(st.session_state.all_data.keys())
            
            col1, col2 = st.columns([1, 3])
            with col1:
                detail_ticker = st.selectbox(
                    "Hisse seçin",
                    ticker_list,
                    format_func=lambda x: f"{config.TICKER_NAMES.get(x, x)} ({x.replace('.IS', '')})"
                )
            with col2:
                period = st.selectbox(
                    "Periyot",
                    ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                    index=1,
                    format_func=lambda x: {"1mo": "1 Ay", "3mo": "3 Ay", "6mo": "6 Ay", "1y": "1 Yıl", "2y": "2 Yıl", "5y": "5 Yıl"}[x]
                )
            
            if detail_ticker:
                fetcher = st.session_state.data_fetcher
                
                with st.spinner("Veri yükleniyor..."):
                    df = fetcher.fetch_single(detail_ticker, period=period)
                
                if df is not None:
                    ti = TechnicalIndicators()
                    df = ti.add_all(df)
                    snapshot = ti.get_snapshot(df)
                    signal = st.session_state.engine.analyze(detail_ticker, df)
                    
                    name = config.TICKER_NAMES.get(detail_ticker, detail_ticker)
                    st.markdown(f"### 📈 {name} ({detail_ticker.replace('.IS', '')})")
                    
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        st.metric("Fiyat", f"₺{snapshot['close']}", delta=f"{snapshot['change_pct']}%")
                    with col2:
                        rsi_color = "green" if snapshot['rsi'] < 30 else "red" if snapshot['rsi'] > 70 else "white"
                        st.markdown(f"**RSI:** :{rsi_color}[{snapshot['rsi']:.0f}]")
                    with col3:
                        vol_color = "green" if snapshot['volume_ratio'] > 1.5 else "red" if snapshot['volume_ratio'] < 0.8 else "white"
                        st.markdown(f"**Hacim:** :{vol_color}[{snapshot['volume_ratio']:.1f}x]")
                    with col4:
                        st.metric("ATR", f"₺{snapshot['atr']:.2f}")
                    with col5:
                        st.metric("Destek", f"₺{snapshot['support']:.2f}")
                    
                    st.divider()
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.plotly_chart(plot_candlestick(df, detail_ticker), use_container_width=True, key="detail_candlestick")
                    with col2:
                        st.plotly_chart(plot_rsi(df), use_container_width=True, key="detail_rsi")
                        st.plotly_chart(plot_volume(df), use_container_width=True, key="detail_volume")
                    
                    st.divider()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("### 📉 Teknik Göstergeler")
                        rsi_zone = "Aşırı Alım" if snapshot['rsi'] > 70 else "Aşırı Satım" if snapshot['rsi'] < 30 else "Nötr"
                        st.write(f"**RSI:** {snapshot['rsi']:.1f} ({rsi_zone})")
                        st.write(f"**SMA Cross:** {snapshot['sma_cross']}")
                        st.write(f"**MACD Cross:** {snapshot['macd_cross']}")
                        st.write(f"**BB Position:** {snapshot['bb_position']}")
                        st.write(f"**Hacim Oranı:** {snapshot['volume_ratio']}x")
                        st.write(f"**Destek:** ₺{snapshot['support']:.2f}")
                        st.write(f"**Direnç:** ₺{snapshot['resistance']:.2f}")
                    
                    with col2:
                        st.markdown("### 🎯 Alım/Satım Sinyali")
                        if signal:
                            color = get_signal_color(signal.signal_type)
                            st.markdown(f"**Sinyal:** :{color}[{signal.signal_type.value}]")
                            st.write(f"**Skor:** {signal.score:+.0f}/100")
                            st.write(f"**Giriş:** ₺{signal.price:.2f}")
                            st.write(f"**Stop-Loss:** ₺{signal.stop_loss:.2f}")
                            st.write(f"**Hedef:** ₺{signal.target_price:.2f}")
                            
                            risk = (signal.price - signal.stop_loss) / signal.price * 100
                            reward = (signal.target_price - signal.price) / signal.price * 100
                            rr = reward / risk if risk > 0 else 0
                            st.write(f"**R/R Oranı:** 1:{rr:.1f}")
                            
                            st.markdown("**Nedenler:**")
                            for r in signal.reasons[:5]:
                                st.write(f"• {r}")
                        else:
                            st.info("Sinyal yok")
                    
                    st.divider()
                    
                    with st.expander("📊 Fiyat Verileri"):
                        st.dataframe(
                            df[['open', 'high', 'low', 'close', 'volume']].tail(30),
                            use_container_width=True
                        )
    
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
                st.plotly_chart(plot_candlestick(df, selected_ticker), use_container_width=True, key="candlestick_chart")
            with col2:
                st.plotly_chart(plot_rsi(df), use_container_width=True, key="rsi_chart")
                st.plotly_chart(plot_volume(df), use_container_width=True, key="volume_chart")
            
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
