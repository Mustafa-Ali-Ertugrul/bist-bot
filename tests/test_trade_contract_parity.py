"""Golden + engine-parity tests for the canonical trade economics contract.

The contract in ``bist_bot.trade_contract`` is the source of truth; the
backtest engine must reproduce it, not the reverse. The engine-parity test is
designed to be FAILING before the engine spread/slippage decomposition fix
and PASSING after it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from bist_bot.backtest import Backtester, CostModel
from bist_bot.risk.costs import CostSchedule
from bist_bot.trade_contract import ExitReason, calculate_trade_outcome
from tests.test_backtest_costs import IdentityIndicators


def zero_schedule() -> CostSchedule:
    return CostSchedule(
        commission_bps=0.0,
        bsmv_pct=0.0,
        exchange_fee_bps=0.0,
        half_spread_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        min_commission_tl=0.0,
        cost_version="zero_test_v1",
    )


def flat_session(close: float) -> tuple[float, float, float, float]:
    return (100.0, 101.0, 99.0, close)


# ---------------------------------------------------------------------------
# Golden contract tests
# ---------------------------------------------------------------------------


def test_zero_cost_identity() -> None:
    sessions = [flat_session(105.0)] * 5
    outcome = calculate_trade_outcome(100.0, None, None, sessions, zero_schedule())
    assert outcome.shares == 1000
    assert outcome.entry_fill == pytest.approx(100.0, abs=1e-9)
    assert outcome.exit_fill == pytest.approx(105.0, abs=1e-9)
    assert outcome.exit_reason is ExitReason.MAX_HOLD
    assert outcome.holding_sessions == 5
    assert outcome.gross_profit_tl == pytest.approx(5000.0, abs=1e-9)
    assert outcome.profit_tl == pytest.approx(5000.0, abs=1e-9)
    assert outcome.total_cost_tl == pytest.approx(0.0, abs=1e-9)


def test_spread_counted_once_as_fill_impact() -> None:
    schedule = CostSchedule(
        commission_bps=0.0,
        bsmv_pct=0.0,
        exchange_fee_bps=0.0,
        half_spread_bps=10.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        min_commission_tl=0.0,
        cost_version="spread_only_test_v1",
    )
    sessions = [flat_session(105.0)] * 5
    outcome = calculate_trade_outcome(100.0, None, None, sessions, schedule)
    assert outcome.shares == 999
    assert outcome.entry_fill == pytest.approx(100.1, abs=1e-9)
    assert outcome.exit_fill == pytest.approx(104.895, abs=1e-9)
    assert outcome.gross_profit_tl == pytest.approx(4995.0, abs=1e-9)
    assert outcome.profit_tl == pytest.approx(4790.205, abs=1e-9)
    assert outcome.spread_impact_tl == pytest.approx(204.795, abs=1e-9)
    assert outcome.total_cost_tl == pytest.approx(204.795, abs=1e-9)


def test_stop_intrabar() -> None:
    sessions = [(100.0, 101.0, 97.9, 99.5)]
    outcome = calculate_trade_outcome(100.0, 98.0, None, sessions, zero_schedule())
    assert outcome.exit_reason is ExitReason.STOP
    assert outcome.exit_ref_price == pytest.approx(98.0, abs=1e-9)
    assert outcome.holding_sessions == 1


def test_stop_gap_open_below_stop() -> None:
    sessions = [(97.0, 99.0, 95.0, 98.0)]
    outcome = calculate_trade_outcome(100.0, 98.0, None, sessions, zero_schedule())
    assert outcome.exit_reason is ExitReason.STOP_GAP
    assert outcome.exit_ref_price == pytest.approx(97.0, abs=1e-9)
    assert outcome.holding_sessions == 1


def test_target_intrabar() -> None:
    sessions = [(100.0, 111.0, 99.0, 105.0)]
    outcome = calculate_trade_outcome(100.0, 95.0, 110.0, sessions, zero_schedule())
    assert outcome.exit_reason is ExitReason.TARGET
    assert outcome.exit_ref_price == pytest.approx(110.0, abs=1e-9)


def test_target_gap_open_above_target() -> None:
    sessions = [(112.0, 113.0, 109.0, 111.0)]
    outcome = calculate_trade_outcome(100.0, 95.0, 110.0, sessions, zero_schedule())
    assert outcome.exit_reason is ExitReason.TARGET_GAP
    assert outcome.exit_ref_price == pytest.approx(112.0, abs=1e-9)
    assert outcome.holding_sessions == 1


def test_same_bar_stop_first() -> None:
    sessions = [(100.0, 120.0, 95.0, 105.0)]
    outcome = calculate_trade_outcome(100.0, 98.0, 110.0, sessions, zero_schedule())
    assert outcome.exit_reason is ExitReason.SAME_BAR_STOP_FIRST
    assert outcome.exit_ref_price == pytest.approx(98.0, abs=1e-9)
    assert outcome.holding_sessions == 1


def test_max_hold_uses_fifth_session_close() -> None:
    sessions = [(100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i) for i in range(7)]
    ids = [f"d{i}" for i in range(7)]
    outcome = calculate_trade_outcome(100.0, None, None, sessions, zero_schedule(), session_ids=ids)
    assert outcome.exit_reason is ExitReason.MAX_HOLD
    assert outcome.exit_ref_price == pytest.approx(104.5, abs=1e-9)
    assert outcome.holding_sessions == 5
    assert outcome.entry_date == "d0"
    assert outcome.exit_date == "d4"


def test_data_end_when_fewer_bars_than_max_hold() -> None:
    sessions = [(100.0, 101.0, 99.0, 101.0 + 0.5 * i) for i in range(3)]
    outcome = calculate_trade_outcome(100.0, None, None, sessions, zero_schedule())
    assert outcome.exit_reason is ExitReason.DATA_END
    assert outcome.exit_ref_price == pytest.approx(102.0, abs=1e-9)
    assert outcome.holding_sessions == 3


def test_bsmv_fee_on_commission_both_sides() -> None:
    schedule = CostSchedule(
        commission_bps=4.0,
        bsmv_pct=5.0,
        exchange_fee_bps=0.0,
        half_spread_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        min_commission_tl=0.0,
        cost_version="bsmv_test_v1",
    )
    sessions = [flat_session(100.0)] * 5
    outcome = calculate_trade_outcome(100.0, None, None, sessions, schedule)
    assert outcome.shares == 999
    assert outcome.commission_tl == pytest.approx(79.92, abs=1e-9)
    assert outcome.bsmv_tl == pytest.approx(outcome.commission_tl * 0.05, abs=1e-9)
    assert outcome.profit_tl == pytest.approx(-(outcome.commission_tl + outcome.bsmv_tl), abs=1e-9)


def test_min_commission_floor_applies_per_side() -> None:
    schedule = CostSchedule(
        commission_bps=4.0,
        bsmv_pct=0.0,
        exchange_fee_bps=0.0,
        half_spread_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        min_commission_tl=50.0,
        cost_version="floor_test_v1",
    )
    sessions = [flat_session(100.0)]
    outcome = calculate_trade_outcome(100.0, None, None, sessions, schedule, notional=10_000.0)
    assert outcome.commission_tl == pytest.approx(100.0, abs=1e-9)
    assert outcome.profit_tl == pytest.approx(-100.0, abs=1e-9)


@pytest.mark.parametrize(
    ("entry_price", "sessions", "stop_price", "target_price", "notional", "max_hold"),
    [
        (0.0, [flat_session(101.0)], None, None, 100_000.0, 5),
        (100.0, [], None, None, 100_000.0, 5),
        (100.0, [flat_session(101.0)], None, None, 0.0, 5),
        (100.0, [flat_session(101.0)], None, None, 100_000.0, 0),
    ],
)
def test_input_validation(
    entry_price: float,
    sessions: list[tuple[float, float, float, float]],
    stop_price: float | None,
    target_price: float | None,
    notional: float,
    max_hold: int,
) -> None:
    with pytest.raises(ValueError):
        calculate_trade_outcome(
            entry_price,
            stop_price,
            target_price,
            sessions,
            zero_schedule(),
            notional=notional,
            max_hold_sessions=max_hold,
        )


def test_session_ids_length_mismatch() -> None:
    with pytest.raises(ValueError):
        calculate_trade_outcome(
            100.0, None, None, [flat_session(101.0)], zero_schedule(), session_ids=["a", "b"]
        )


# ---------------------------------------------------------------------------
# Engine parity
# ---------------------------------------------------------------------------

PARITY_CM = CostModel(
    commission_bps=4.0,
    bsmv_bps=0.0,
    exchange_fee_bps=0.55,
    stamp_tax_bps=0.0,
    spread_bps=3.0,
    slippage_model="fixed",
    fixed_slippage_bps=2.0,
)

PARITY_SCHEDULE = CostSchedule(
    commission_bps=4.0,
    bsmv_pct=0.0,
    exchange_fee_bps=0.55,
    half_spread_bps=3.0,
    slippage_bps=2.0,
    stamp_tax_bps=0.0,
    min_commission_tl=0.0,
    cost_version="parity_test_v1",
)


class ParityBacktester(Backtester):
    """Enters on the first bar, exits on the 6th bar, never stops/targets."""

    def __init__(self, cost_model: CostModel | None = None):
        super().__init__(
            initial_capital=10_000,
            indicators=IdentityIndicators(),
            cost_model=cost_model,
        )

    def _build_signal_context(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
        _ = ticker
        if len(history) == 1:
            return {
                "enter": True,
                "exit": False,
                "score": 25.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
            }
        if len(history) == 6:
            return {
                "enter": False,
                "exit": True,
                "score": 0.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
            }
        return {
            "enter": False,
            "exit": False,
            "score": 0.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        }


def build_parity_frame() -> pd.DataFrame:
    """7-row scripted frame. The engine loop starts at index 1 and passes
    ``df.iloc[:i]`` (current bar excluded) to the signal builder, so:
    - row 0 is inert (it only makes history non-empty at i==1),
    - the entry fires at index 1 (open 100.0),
    - the exit fires at index 6 (open 103.0); close[5] == open[6] == 103.0
      so the engine exit reference equals the contract MAX_HOLD reference.
    """
    opens = [100.0, 100.6, 101.2, 101.8, 102.4, 103.0]
    closes = [100.6, 101.2, 101.8, 102.4, 103.0, 103.2]
    rows = []
    rows.append(
        {
            "date": datetime(2024, 1, 1),
            "open": 99.4,
            "high": 99.45,
            "low": 99.35,
            "close": 99.4,
            "volume": 1_000,
            "volume_sma_20": 1_000,
            "atr": 4.0,
            "rsi": 50.0,
            "sma_20": 99.4,
        }
    )
    for idx, (open_p, close_p) in enumerate(zip(opens, closes, strict=True), start=1):
        rows.append(
            {
                "date": datetime(2024, 1, 1) + timedelta(days=idx),
                "open": open_p,
                "high": max(open_p, close_p) + 0.05,
                "low": min(open_p, close_p) - 0.05,
                "close": close_p,
                "volume": 1_000,
                "volume_sma_20": 1_000,
                "atr": 4.0,
                "rsi": 50.0,
                "sma_20": open_p,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def parity_sessions() -> list[tuple[float, float, float, float]]:
    frame = build_parity_frame()
    window = frame.iloc[1:7]  # the 6 scripted parity bars only
    return [(row.open, row.high, row.low, row.close) for row in window.itertuples(index=False)]


def pad_engine_frame(frame: pd.DataFrame, total_rows: int = 54) -> pd.DataFrame:
    """Append inert flat bars: the engine demands >=50 rows, but only the
    scripted window of the frame carries the entry/exit."""
    missing = total_rows - len(frame)
    assert missing > 0, "pad target must exceed scripted frame length"
    last_date = frame.index[-1]
    filler = pd.DataFrame(
        {
            "date": [last_date + timedelta(days=i + 1) for i in range(missing)],
            "open": 103.2,
            "high": 103.25,
            "low": 103.15,
            "close": 103.2,
            "volume": 1_000,
            "volume_sma_20": 1_000,
            "atr": 4.0,
            "rsi": 50.0,
            "sma_20": 103.2,
        }
    ).set_index("date")
    return pd.concat([frame, filler])


def test_engine_matches_contract_parity() -> None:
    frame = pad_engine_frame(build_parity_frame())
    engine = ParityBacktester(cost_model=PARITY_CM)
    result = engine.run("TEST.IS", frame, verbose=False)
    assert result is not None
    trades = result.trades
    assert len(trades) == 1
    trade = trades[0]

    outcome = calculate_trade_outcome(
        100.0, None, None, parity_sessions(), PARITY_SCHEDULE, notional=10_000.0
    )

    # Reference prices match by construction (100.0 -> 103.0).
    assert outcome.exit_reason is ExitReason.MAX_HOLD
    assert outcome.shares == 99

    # Fill prices: entry 100.05, exit 102.9485.
    assert trade.entry_price == pytest.approx(100.05, abs=1e-4)
    assert trade.exit_price == pytest.approx(102.9485, abs=1e-4)
    assert outcome.entry_fill == pytest.approx(100.05, abs=1e-9)
    assert outcome.exit_fill == pytest.approx(102.9485, abs=1e-9)

    # Notional + shares equivalence.
    assert trade.entry_notional_tl == pytest.approx(9904.95, abs=0.02)
    assert trade.entry_notional_tl / trade.entry_price == pytest.approx(99.0, abs=0.01)
    assert outcome.notional_tl == pytest.approx(outcome.shares * outcome.entry_fill, abs=1e-9)

    # P&L decomposition: engine must match the contract.
    assert trade.gross_profit_tl == pytest.approx(297.0, abs=0.02)
    assert trade.profit_tl == pytest.approx(277.81, abs=0.05)
    assert outcome.gross_profit_tl == pytest.approx(297.0, abs=1e-9)
    assert outcome.profit_tl == pytest.approx(277.80743, abs=1e-5)

    # Cost decomposition: spread/slippage only inside fills, cash fees additive.
    assert trade.spread_cost_tl == pytest.approx(6.03, abs=0.02)
    assert trade.slippage_tl == pytest.approx(4.02, abs=0.02)
    assert trade.commission_tl == pytest.approx(8.04, abs=0.02)
    assert trade.exchange_fee_tl == pytest.approx(1.11, abs=0.02)
    assert outcome.spread_impact_tl == pytest.approx(6.0291, abs=1e-9)
    assert outcome.slippage_impact_tl == pytest.approx(4.0194, abs=1e-9)
    assert outcome.commission_tl == pytest.approx(8.0387406, abs=1e-6)
    assert outcome.exchange_fee_tl == pytest.approx(1.1053268325, abs=1e-6)

    # Holding period: engine reports calendar days (5 daily bars) matching
    # contract holding sessions on a daily frame.
    assert trade.holding_days == outcome.holding_sessions == 5
