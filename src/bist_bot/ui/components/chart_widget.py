from __future__ import annotations

from collections.abc import Sequence

import plotly.graph_objects as go
import streamlit as st


def _format_axis_label(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%b %d<br>%Y")
    return str(value)


def _continuous_x_axis(index: Sequence) -> tuple[list[str], dict]:
    """Use evenly spaced categories so missing market dates do not leave gaps."""
    x_values = [str(i) for i in range(len(index))]
    if not x_values:
        return x_values, dict(type="category")

    target_ticks = min(6, len(x_values))
    step = max(1, (len(x_values) - 1) // max(1, target_ticks - 1))
    tick_indexes = list(range(0, len(x_values), step))
    if tick_indexes[-1] != len(x_values) - 1:
        tick_indexes.append(len(x_values) - 1)

    return x_values, dict(
        type="category",
        tickmode="array",
        tickvals=[x_values[i] for i in tick_indexes],
        ticktext=[_format_axis_label(index[i]) for i in tick_indexes],
    )


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
    x_values, xaxis = _continuous_x_axis(df.index)
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=x_values,
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
                x=x_values,
                y=df["sma_20"],
                mode="lines",
                name="SMA 20",
                line=dict(color="#adc6ff", width=2),
            )
        )
    if "ema_50" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=df["ema_50"],
                mode="lines",
                name="EMA 50",
                line=dict(color="#ffb4aa", width=2),
            )
        )
    base_layout = _base_layout(440)
    fig.update_layout({
        **base_layout,
        "xaxis": {**base_layout["xaxis"], **xaxis},
        "xaxis_rangeslider_visible": False,
        "legend": dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    })
    return fig


def plot_volume(df):
    x_values, xaxis = _continuous_x_axis(df.index)
    colors = [
        "#48ddbc" if df["close"].iloc[i] >= df["open"].iloc[i] else "#ff796c"
        for i in range(len(df))
    ]
    base_layout = _base_layout(180)
    fig = go.Figure(data=[go.Bar(x=x_values, y=df["volume"], marker_color=colors)])
    fig.update_layout({
        **base_layout,
        "xaxis": {**base_layout["xaxis"], **xaxis},
        "showlegend": False,
    })
    return fig


def plot_rsi(df):
    x_values, xaxis = _continuous_x_axis(df.index)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=x_values, y=df["rsi"], mode="lines", line=dict(color="#48ddbc", width=2))
    )
    fig.add_hrect(y0=0, y1=30, fillcolor="green", opacity=0.08, line_width=0)
    fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.08, line_width=0)
    fig.add_hline(y=50, line_dash="dash", line_color="#8b90a0")
    base_layout = _base_layout(180)
    fig.update_layout({
        **base_layout,
        "xaxis": {**base_layout["xaxis"], **xaxis},
        "yaxis": {**base_layout["yaxis"], "range": [0, 100]},
        "showlegend": False,
    })
    return fig


def render_chart(fig, key: str) -> None:
    st.plotly_chart(fig, use_container_width=True, key=key)
