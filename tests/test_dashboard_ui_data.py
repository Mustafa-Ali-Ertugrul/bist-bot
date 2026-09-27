"""Data helpers behind the web UI: 4h bars, pivots, latest signal-batch breadth."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from bist_bot.dashboard import (
    _latest_signal_batch_breadth,
    _previous_period_pivots,
    _resample_session_4h,
    _session_summary,
)


def _hourly_session(day: str, base: float) -> pd.DataFrame:
    """60m bars as the fetcher returns them: UTC-naive, 10:00-17:00 TR + 18:00 auction."""
    idx = pd.date_range(f"{day} 07:00", periods=9, freq="h")  # 07..15 UTC = 10..18 TR
    closes = [base + i for i in range(9)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [100] * 8 + [0],
        },
        index=idx,
    )


def test_resample_session_4h_splits_each_session_in_two_bars():
    df = pd.concat([_hourly_session("2026-09-24", 100), _hourly_session("2026-09-25", 200)])
    bars = _resample_session_4h(df)
    assert len(bars) == 4
    # Bar starts are 10:00 and 14:00 Istanbul time (07:00 / 11:00 UTC).
    assert [str(ts) for ts in bars.index[:2]] == ["2026-09-24 07:00:00", "2026-09-24 11:00:00"]
    morning, afternoon = bars.iloc[0], bars.iloc[1]
    assert morning["open"] == 100 and morning["close"] == 103 and morning["volume"] == 400
    # The 18:00 closing-auction print joins the afternoon bar.
    assert afternoon["close"] == 108 and afternoon["high"] == 108.5
    assert afternoon["volume"] == 400


def test_pivots_use_last_completed_session_while_market_is_open():
    df = pd.concat([_hourly_session("2026-09-24", 100), _hourly_session("2026-09-25", 200)])
    during_session = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)  # 12:00 TR
    pivots = _previous_period_pivots(df, intraday=True, now=during_session)
    assert pivots is not None
    assert pivots["basis_date"] == "2026-09-24"
    high, low, close = 108.5, 99.5, 108.0
    pp = (high + low + close) / 3
    assert pivots["pp"] == round(pp, 2)
    assert pivots["r1"] == round(2 * pp - low, 2)
    assert pivots["s1"] == round(2 * pp - high, 2)


def test_pivots_use_today_after_the_close():
    df = pd.concat([_hourly_session("2026-09-24", 100), _hourly_session("2026-09-25", 200)])
    weekend = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    pivots = _previous_period_pivots(df, intraday=True, now=weekend)
    assert pivots is not None and pivots["basis_date"] == "2026-09-25"


def test_session_summary_is_the_whole_last_day_not_the_last_bar():
    df = pd.concat([_hourly_session("2026-09-24", 100), _hourly_session("2026-09-25", 200)])
    summary = _session_summary(df, intraday=True)
    assert summary == {"date": "2026-09-25", "high": 208.5, "low": 199.5}


def test_breadth_counts_only_latest_batch_buys_and_has_no_invented_defaults():
    signals = [
        {
            "ticker": "ENERY.IS",
            "signal_type": "🟡 ZAYIF AL",
            "timestamp": "2026-09-27T16:50:26+00:00",
            "reasons": ["RSI yüksek (71.9)", "Fiyat-Hacim yükseliş onayı"],
        },
        {
            "ticker": "THYAO.IS",
            "signal_type": "🟠 ZAYIF SAT",
            "timestamp": "2026-09-27T16:50:30+00:00",
            "reasons": ["RSI nötr (41.2)"],
        },
        {  # an older batch must not leak into the summary
            "ticker": "HALKB.IS",
            "signal_type": "🟢 AL",
            "timestamp": "2026-09-24T14:30:00+00:00",
            "reasons": ["RSI nötr (50.0)"],
        },
    ]
    breadth = _latest_signal_batch_breadth(signals)
    assert breadth["batch_at"] == "2026-09-27T16:50:30+00:00"
    assert breadth["buy_tickers"] == ["ENERY"]
    assert breadth["signal_count"] == 2
    assert breadth["avg_rsi"] == round((71.9 + 41.2) / 2, 1)
    assert breadth["volume_confirmed"] == 1

    empty = _latest_signal_batch_breadth([])
    assert empty["avg_rsi"] is None
    assert empty["buy_tickers"] == []
