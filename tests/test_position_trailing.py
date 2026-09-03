"""Unit tests for the Deney M ATR trailing stop in PositionManager.

Trail semantics (docs/retail_abone_ekonomisi.md §17):
    trail = peak_close_since_entry - TRAILING_ATR_MULT * ATR14
    trail only ever tightens (never below the original stop), is persisted
    via _update_stop_loss, and a hit on a ratcheted stop exits with
    ExitReason.TRAILING_STOP.
"""

from unittest.mock import MagicMock

import pytest

from bist_bot.agent.position_manager import PositionManager
from bist_bot.agent.state_machine import ExitReason


def _pos(
    position_id: int = 1,
    ticker: str = "THYAO",
    entry_price: float = 100.0,
    stop_loss: float = 90.0,
    target_price: float = 200.0,
    entry_time: str = "2026-08-20T09:30:00+00:00",
) -> dict:
    return {
        "id": position_id,
        "ticker": ticker,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "entry_time": entry_time,
        "exit_price": None,
        "state": "OPEN",
        "quantity": 100,
    }


def _closes(*values: float, start_day: int = 20) -> list[tuple[str, float]]:
    return [(f"2026-08-{start_day + i:02d}", v) for i, v in enumerate(values)]


@pytest.fixture
def manager():
    db = MagicMock()
    settings = MagicMock()
    settings.agent.TRAILING_STOP_ENABLED = True
    settings.agent.TRAILING_ATR_MULT = 3.0
    pm = PositionManager(db, settings)
    return pm


class TestATRTrailing:
    def test_rising_price_ratchets_stop_and_persists(self, manager):
        """peak 110, ATR 2 -> trail 104 > original 90 -> stop updated."""
        manager.get_open_positions = MagicMock(return_value=[_pos()])
        updated: dict = {}
        manager._update_stop_loss = MagicMock(
            side_effect=lambda pid, stop: updated.update(id=pid, stop=stop)
        )

        prices = {"THYAO": 105.0}
        atr_map = {"THYAO": 2.0}
        closes_map = {"THYAO": _closes(100.0, 110.0)}

        triggers = manager.check_exit_conditions(prices, atr_map=atr_map, closes_map=closes_map)

        assert triggers == []  # 105 > 104, no exit
        manager._update_stop_loss.assert_called_once_with(1, 104.0)
        assert updated == {"id": 1, "stop": 104.0}

    def test_trail_never_loosens_below_original_stop(self, manager):
        """peak = current price, trail 94 < original 90? no: 100-18=82 < 90 -> keep original."""
        manager.get_open_positions = MagicMock(return_value=[_pos()])
        manager._update_stop_loss = MagicMock()

        prices = {"THYAO": 100.0}
        atr_map = {"THYAO": 6.0}  # trail = 100 - 18 = 82 < 90
        closes_map = {"THYAO": _closes(100.0)}

        manager.check_exit_conditions(prices, atr_map=atr_map, closes_map=closes_map)

        manager._update_stop_loss.assert_not_called()

    def test_gap_down_below_fresh_trail_exits_as_trailing_stop(self, manager):
        """Same-cycle ratchet + gap-down: trail 104 rises above stop 90 while
        the price already fell to 103.5 -> TRAILING_STOP (not STOP_HIT)."""
        manager.get_open_positions = MagicMock(return_value=[_pos()])
        manager._update_stop_loss = MagicMock()

        prices = {"THYAO": 103.5}
        atr_map = {"THYAO": 2.0}
        closes_map = {"THYAO": _closes(110.0)}

        triggers = manager.check_exit_conditions(prices, atr_map=atr_map, closes_map=closes_map)

        assert len(triggers) == 1
        assert triggers[0]["exit_reason"] == ExitReason.TRAILING_STOP.value
        manager._update_stop_loss.assert_called_once_with(1, 104.0)

    def test_later_cycle_hit_on_ratcheted_stop_reports_stop_hit(self, manager):
        """A hit on a stop that was ratcheted in an earlier cycle reports
        STOP_HIT (the original stop is not stored; the DB stop_loss value
        itself carries the trail level)."""
        manager.get_open_positions = MagicMock(return_value=[_pos(stop_loss=104.0)])
        manager._update_stop_loss = MagicMock()

        prices = {"THYAO": 103.0}
        atr_map = {"THYAO": 2.0}
        closes_map = {"THYAO": _closes(110.0)}

        triggers = manager.check_exit_conditions(prices, atr_map=atr_map, closes_map=closes_map)

        assert len(triggers) == 1
        assert triggers[0]["exit_reason"] == ExitReason.STOP_HIT.value
        manager._update_stop_loss.assert_not_called()

    def test_original_stop_hit_still_reports_stop_hit(self, manager):
        """Trail unavailable (no ATR) -> hit on original stop is STOP_HIT."""
        manager.get_open_positions = MagicMock(return_value=[_pos()])
        manager._update_stop_loss = MagicMock()

        triggers = manager.check_exit_conditions({"THYAO": 89.0}, atr_map={}, closes_map={})

        assert len(triggers) == 1
        assert triggers[0]["exit_reason"] == ExitReason.STOP_HIT.value

    def test_trailing_disabled_keeps_original_stop(self, manager):
        manager.get_open_positions = MagicMock(return_value=[_pos()])
        manager._update_stop_loss = MagicMock()
        manager.settings.agent.TRAILING_STOP_ENABLED = False

        triggers = manager.check_exit_conditions(
            {"THYAO": 105.0}, atr_map={"THYAO": 2.0}, closes_map={"THYAO": _closes(110.0)}
        )

        manager._update_stop_loss.assert_not_called()
        assert triggers == []

    def test_ignores_closes_before_entry_date(self, manager):
        """Peak must only consider closes at/after entry (look-ahead safe)."""
        manager.get_open_positions = MagicMock(
            return_value=[_pos(entry_time="2026-08-25T09:30:00+00:00")]
        )
        manager._update_stop_loss = MagicMock()

        # Old high 140 before entry must not set the peak; post-entry max 106
        # -> trail = 106 - 6 = 100, stored stop 90 -> ratchet to 100.
        closes = [("2026-08-21", 140.0), ("2026-08-25", 100.0), ("2026-08-26", 106.0)]
        triggers = manager.check_exit_conditions(
            {"THYAO": 105.0}, atr_map={"THYAO": 2.0}, closes_map={"THYAO": closes}
        )

        assert triggers == []
        manager._update_stop_loss.assert_called_once_with(1, 100.0)

    def test_missing_atr_entry_skips_trailing(self, manager):
        manager.get_open_positions = MagicMock(return_value=[_pos()])
        manager._update_stop_loss = MagicMock()

        manager.check_exit_conditions(
            {"THYAO": 105.0}, atr_map={}, closes_map={"THYAO": _closes(110.0)}
        )

        manager._update_stop_loss.assert_not_called()
