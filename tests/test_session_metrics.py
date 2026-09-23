"""session_metrics testleri: saf fonksiyonlar + kural kapilari."""

from datetime import datetime

import pandas as pd

from bist_bot.market_calendar import TR
from bist_bot.strategy.session_metrics import (
    SessionStats,
    apply_session_adjustment,
    sector_medians,
    session_stats,
    today_slice,
    universe_breadth,
)

NOW = datetime(2026, 9, 17, 14, 30, tzinfo=TR)


def _trigger(opens, highs, lows, closes, vols, day="2026-09-17"):
    idx = pd.DatetimeIndex(
        [pd.Timestamp(f"{day} {10 + i // 4:02d}:{(i % 4) * 15:02d}") for i in range(len(closes))]
    )
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


def _daily(closes, vols):
    idx = pd.DatetimeIndex([pd.Timestamp(f"2026-09-{10 + i:02d}") for i in range(len(closes))])
    return pd.DataFrame({"close": closes, "volume": vols}, index=idx)


class P:
    session_adj_enabled = True
    session_limit_down_block = True
    session_limit_up_penalty = 6.0
    session_range_pos_min = 0.8
    session_recovery_min_pct = 2.0
    session_recovery_bonus = 4.0
    session_rel_threshold = 2.0
    session_rel_bonus = 3.0
    session_pace_min = 1.5
    session_pace_bonus = 2.0
    session_breadth_min_pct = 40.0
    session_breadth_penalty = 4.0
    session_max_bonus = 8.0
    session_max_penalty = 8.0


def _stats(**kw):
    base = dict(
        day_change_pct=1.0,
        range_position=0.5,
        dip_pct=-1.0,
        recovery_pct=1.0,
        volume_pace=1.0,
        limited_down=False,
        limited_up=False,
    )
    base.update(kw)
    return SessionStats(**base)


def test_today_slice_filters_tr_date():
    df = _trigger([100] * 6, [101] * 6, [99] * 6, [100] * 6, [1000] * 6)
    assert len(today_slice(df, NOW)) == 6
    assert today_slice(None, NOW).empty
    assert today_slice(pd.DataFrame(), NOW).empty


def test_today_slice_tz_naive_safe():
    df = _trigger([100] * 4, [101] * 4, [99] * 4, [100] * 4, [1000] * 4)
    df.index = df.index.tz_localize(None)
    assert len(today_slice(df, NOW)) == 4


def test_session_stats_recovery_math():
    trig = _trigger(
        [100, 101, 102, 103],
        [101, 102, 103, 106],
        [99, 100, 101, 102],
        [100, 101, 102, 105.5],
        [1000] * 4,
    )
    daily = _daily([90.0] * 19 + [100.0, 100.0], [100000.0] * 21)
    s = session_stats(trig, daily, NOW)
    assert s.day_change_pct == abs(s.day_change_pct) and abs(s.day_change_pct - 5.5) < 0.01
    assert abs(s.dip_pct - (-1.0)) < 0.01
    assert abs(s.recovery_pct - 6.57) < 0.1
    assert abs(s.range_position - (105.5 - 99) / (106 - 99)) < 0.01
    assert s.volume_pace is not None and s.volume_pace > 0
    assert s.limited_down is False and s.limited_up is False


def test_session_stats_limit_flags():
    trig = _trigger([100], [100], [90], [90.0], [500])
    daily = _daily([100.0] * 20 + [100.0], [100000.0] * 21)
    s = session_stats(trig, daily, NOW)
    assert s.limited_down is True
    trig2 = _trigger([100], [110], [100], [110.0], [500])
    s2 = session_stats(trig2, daily, NOW)
    assert s2.limited_up is True


def test_session_stats_no_data():
    s = session_stats(None, None, NOW)
    assert s.day_change_pct is None and s.range_position is None
    assert s.limited_down is False and s.limited_up is False


def test_universe_breadth():
    b = universe_breadth({"A": 2.0, "B": -1.0, "C": 0.0, "D": 3.0})
    assert b["n"] == 4 and abs(b["adv_pct"] - 50.0) < 1e-9
    assert b["median"] is not None
    e = universe_breadth({})
    assert e == {"n": 0, "adv_pct": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0}


def test_sector_medians_diger_bucket():
    m = sector_medians({"A.IS": 4.0, "B.IS": 2.0, "C.IS": -3.0}, {"A.IS": "BANKA"})
    assert m["BANKA"] == 4.0
    assert m["DIGER"] == -0.5


def test_block_limit_down():
    d, r, blocked = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(day_change_pct=-10.0, limited_down=True),
        sector_rel=None,
        breadth_adv_pct=80.0,
        score=30.0,
    )
    assert blocked is True and d == 0.0 and any("Taban" in x for x in r)


def test_penalty_limit_up():
    d, r, blocked = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(day_change_pct=9.8, limited_up=True),
        sector_rel=None,
        breadth_adv_pct=80.0,
        score=30.0,
    )
    assert blocked is False and d == -6.0


def test_bonus_recovery():
    d, r, blocked = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(day_change_pct=3.0, range_position=0.9, recovery_pct=4.0),
        sector_rel=None,
        breadth_adv_pct=80.0,
        score=30.0,
    )
    assert blocked is False and d == 4.0


def test_sector_relative_both_sides():
    d1, _, _ = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(day_change_pct=1.0),
        sector_rel=3.5,
        breadth_adv_pct=80.0,
        score=30.0,
    )
    assert d1 == 3.0
    d2, _, _ = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(day_change_pct=1.0),
        sector_rel=-3.5,
        breadth_adv_pct=80.0,
        score=30.0,
    )
    assert d2 == -3.0


def test_breadth_penalty_and_cap():
    d, _, _ = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(day_change_pct=9.8, limited_up=True, range_position=0.95, recovery_pct=9.0),
        sector_rel=5.0,
        breadth_adv_pct=20.0,
        score=30.0,
    )
    # -6 (tavan) +4 (toparlanma) +3 (sektor) +0 (pace 1.0 notr) -4 (breadth) = -3
    assert d == -3.0


def test_cap_clamp():
    class Big(P):
        session_max_bonus = 5.0

    d, _, _ = apply_session_adjustment(
        params=Big(),
        ticker="X.IS",
        stats=_stats(day_change_pct=3.0, range_position=0.95, recovery_pct=9.0, volume_pace=3.0),
        sector_rel=5.0,
        breadth_adv_pct=80.0,
        score=30.0,
    )
    assert d == 5.0


def test_disabled_and_nonpositive_noop():
    d, r, b = apply_session_adjustment(
        params=type("Q", (), {"session_adj_enabled": False})(),
        ticker="X.IS",
        stats=_stats(day_change_pct=-10.0, limited_down=True),
        sector_rel=None,
        breadth_adv_pct=10.0,
        score=30.0,
    )
    assert (d, r, b) == (0.0, [], False)
    d2, r2, b2 = apply_session_adjustment(
        params=P(),
        ticker="X.IS",
        stats=_stats(limited_down=True, day_change_pct=-10.0),
        sector_rel=None,
        breadth_adv_pct=80.0,
        score=-5.0,
    )
    assert (d2, r2, b2) == (0.0, [], False)
