from __future__ import annotations

import pandas as pd

from bist_bot.ui.components.chart_widget import plot_candlestick, plot_macd, plot_rsi, plot_volume


def _sample_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [11.5, 12.2, 13.0],
            "low": [9.8, 10.5, 11.7],
            "close": [11.0, 10.8, 12.6],
            "volume": [1000, 1200, 900],
            "rsi": [42.0, 51.0, 64.0],
            "sma_20": [10.5, 10.8, 11.4],
            "sma_50": [10.3, 10.6, 10.9],
            "macd": [0.1, 0.2, 0.3],
            "macd_signal": [0.05, 0.12, 0.18],
            "macd_histogram": [0.05, 0.08, 0.12],
        },
        index=pd.to_datetime(["2026-05-16", "2026-05-18", "2026-05-20"]),
    )


def test_candlestick_uses_continuous_category_axis_for_missing_dates() -> None:
    fig = plot_candlestick(_sample_price_frame(), "TEST.IS")

    assert fig.layout.xaxis.type == "category"
    assert tuple(fig.data[0].x) == ("0", "1", "2")
    assert tuple(fig.data[1].x) == ("0", "1", "2")
    assert "fiyat grafiği" in fig.layout.title.text
    assert any(trace.name == "SMA 50" for trace in fig.data)


def test_indicator_charts_use_continuous_category_axis_for_missing_dates() -> None:
    df = _sample_price_frame()

    volume = plot_volume(df)
    rsi = plot_rsi(df)
    macd = plot_macd(df)

    assert volume.layout.xaxis.type == "category"
    assert tuple(volume.data[0].x) == ("0", "1", "2")
    assert "Hacim grafiği" in volume.layout.title.text
    assert rsi.layout.xaxis.type == "category"
    assert tuple(rsi.data[0].x) == ("0", "1", "2")
    assert rsi.layout.title.text == "RSI (14)"
    assert macd.layout.xaxis.type == "category"
    assert macd.layout.title.text == "MACD"
