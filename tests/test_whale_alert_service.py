from __future__ import annotations

import pandas as pd

from bist_bot.services.whale_alert_service import build_whale_alerts
from bist_bot.strategy.signal_models import Signal, SignalType


def _frame(*, last_close: float = 112.0, last_volume: int = 900_000) -> pd.DataFrame:
    rows = 40
    closes = [100.0 + (idx * 0.1) for idx in range(rows - 1)] + [last_close]
    volumes = [100_000 for _ in range(rows - 1)] + [last_volume]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2026-05-01", periods=rows, freq="15min"),
    )


def test_build_whale_alerts_flags_volume_and_price_anomaly():
    signal = Signal(
        ticker="THYAO.IS",
        signal_type=SignalType.STRONG_BUY,
        score=72,
        price=112.0,
    )

    alerts = build_whale_alerts({"THYAO.IS": _frame()}, [signal], min_score=45)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.ticker == "THYAO.IS"
    assert alert.score >= 80
    assert alert.direction == "Toplama izi"
    assert any("Hacim" in reason for reason in alert.reasons)
    assert any("Mevcut model" in reason for reason in alert.reasons)


def test_build_whale_alerts_skips_quiet_assets():
    alerts = build_whale_alerts(
        {"ASELS.IS": _frame(last_close=104.0, last_volume=100_000)},
        [],
        min_score=45,
    )

    assert alerts == []


def test_app_shell_exposes_whale_radar_page():
    from bist_bot.ui.components.app_shell import PAGE_META

    assert PAGE_META["whale"]["label"] == "Balina Radar"
