from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from bist_bot.services.whale_alert_service import build_whale_alerts
from bist_bot.strategy.signal_models import Signal, SignalType
from bist_bot.ui.components.app_shell import PAGE_META


def _enriched_frame(obv_trend: str = "UP") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "close": 100.0,
                "volume_ratio": 1.0,
                "rsi": 52.0,
                "adx": 18.0,
                "support": 95.0,
                "resistance": 130.0,
                "obv_trend": "FLAT",
            },
            {
                "close": 106.0,
                "volume_ratio": 4.2,
                "rsi": 72.0,
                "adx": 31.0,
                "support": 98.0,
                "resistance": 106.5,
                "obv_trend": obv_trend,
            },
        ]
    )


def test_build_whale_alerts_scores_existing_scan_data_with_obv_alias() -> None:
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.BUY,
        score=36.0,
        price=103.2,
    )
    frame = _enriched_frame(obv_trend="UP").assign(
        close=[100.0, 103.2],
        volume_ratio=[1.0, 2.6],
        rsi=[52.0, 52.0],
        adx=[18.0, 18.0],
        resistance=[130.0, 130.0],
    )

    with patch("bist_bot.services.whale_alert_service.TechnicalIndicators") as indicators:
        indicators.return_value.add_all.return_value = frame

        alerts = build_whale_alerts({"THYAO.IS": pd.DataFrame({"close": [100.0, 106.0]})}, [signal])

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.ticker == "THYAO.IS"
    assert alert.score == 64
    assert alert.direction == "Toplama izi"
    assert alert.severity == "Orta"
    assert "OBV trendi: rising" in alert.reasons


def test_build_whale_alerts_accepts_trigger_frame_and_orders_by_score() -> None:
    low_frame = _enriched_frame(obv_trend="FLAT").assign(
        volume_ratio=[1.0, 1.8],
        close=[100.0, 102.0],
        adx=[18.0, 18.0],
        resistance=[130.0, 130.0],
        rsi=[52.0, 52.0],
    )

    def add_all(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.attrs.get("kind") == "low":
            return low_frame
        return _enriched_frame(obv_trend="DOWN")

    low_raw = pd.DataFrame({"close": [100.0, 102.0]})
    low_raw.attrs["kind"] = "low"
    high_raw = pd.DataFrame({"close": [100.0, 106.0]})

    with patch("bist_bot.services.whale_alert_service.TechnicalIndicators") as indicators:
        indicators.return_value.add_all.side_effect = add_all

        alerts = build_whale_alerts(
            {
                "LOW.IS": {"trigger": low_raw},
                "HIGH.IS": high_raw,
            },
            [],
            min_score=20,
        )

    assert [alert.ticker for alert in alerts] == ["HIGH.IS", "LOW.IS"]
    assert alerts[0].direction == "Toplama izi"
    assert alerts[1].direction == "Olagandisi izleme"


def test_whale_page_is_registered_and_renders_service_results() -> None:
    assert PAGE_META["whale"]["label"] == "Balina Radar"

    from bist_bot.ui.pages import whale_alerts_page

    class StreamlitStub(SimpleNamespace):
        def __enter__(self) -> StreamlitStub:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    alert = SimpleNamespace(
        ticker="THYAO.IS",
        score=87,
        direction="Toplama izi",
        severity="Yuksek",
        price=106.0,
        change_pct=6.0,
        volume_ratio=4.2,
        signal_score=62.0,
        reasons=["Hacim ortalamanin ustunde"],
        action_note="Izleme listesine al",
    )
    session_state = {
        "all_data": {"THYAO.IS": object()},
        "signals": [object()],
        "scan_in_progress": False,
    }
    streamlit = StreamlitStub(
        session_state=session_state,
        title=lambda *_args, **_kwargs: None,
        caption=lambda *_args, **_kwargs: None,
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        metric=lambda *_args, **_kwargs: None,
        subheader=lambda *_args, **_kwargs: None,
        markdown=lambda *_args, **_kwargs: None,
    )
    streamlit.columns = lambda spec: [streamlit] * (spec if isinstance(spec, int) else len(spec))
    streamlit.container = lambda **_kwargs: streamlit

    with (
        patch.object(whale_alerts_page, "st", streamlit),
        patch.object(whale_alerts_page, "build_whale_alerts", return_value=[alert]) as build,
    ):
        whale_alerts_page.render_whale_alerts_page()

    build.assert_called_once_with(session_state["all_data"], session_state["signals"])


def test_streamlit_app_keeps_running_if_whale_page_is_missing() -> None:
    from bist_bot import streamlit_app

    source = inspect.getsource(streamlit_app)

    assert 'exc.name != "bist_bot.ui.pages.whale_alerts_page"' in source
    assert "Balina Radar ekranı bu dağıtım paketinde bulunamadı" in source
