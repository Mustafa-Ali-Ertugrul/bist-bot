from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st


def _base_layout(height: int) -> dict:
    return dict(
        template="plotly_dark",
        height=height,
        margin=dict(l=12, r=12, t=24, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0f1722",
        font=dict(color="#eef3ff", family="Inter, sans-serif"),
        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)", zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)", zeroline=False),
    )


def plot_candlestick(df, ticker: str):
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
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["sma_20"],
                mode="lines",
                name="SMA 20",
                line=dict(color="#adc6ff", width=2),
            )
        )
    if "ema_50" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["ema_50"],
                mode="lines",
                name="EMA 50",
                line=dict(color="#ffb4aa", width=2),
            )
        )
    fig.update_layout(
        **_base_layout(440),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def plot_volume(df):
    colors = [
        "#48ddbc" if df["close"].iloc[i] >= df["open"].iloc[i] else "#ff796c"
        for i in range(len(df))
    ]
    fig = go.Figure(data=[go.Bar(x=df.index, y=df["volume"], marker_color=colors)])
    fig.update_layout(**_base_layout(180), showlegend=False)
    return fig


def plot_rsi(df):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=df.index, y=df["rsi"], mode="lines", line=dict(color="#48ddbc", width=2))
    )
    fig.add_hrect(y0=0, y1=30, fillcolor="green", opacity=0.08, line_width=0)
    fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.08, line_width=0)
    fig.add_hline(y=50, line_dash="dash", line_color="#8b90a0")
    base_layout = _base_layout(180)
    fig.update_layout(
        **base_layout,
        yaxis={**base_layout["yaxis"], "range": [0, 100]},
        showlegend=False,
    )
    return fig


def render_chart(fig, key: str) -> None:
    st.plotly_chart(fig, use_container_width=True, key=key)
