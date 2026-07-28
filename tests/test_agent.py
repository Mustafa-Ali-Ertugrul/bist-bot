from unittest.mock import MagicMock

import pytest

from bist_bot.agent.state_machine import (
    AgentOperationalState,
    ExitReason,
    PositionState,
)


class TestStateMachine:
    def test_position_state_values(self):
        assert PositionState.POSITION_OPEN.value == "POSITION_OPEN"
        assert PositionState.CLOSED.value == "CLOSED"
        assert PositionState.ENTRY_ORDERED.value == "ENTRY_ORDERED"

    def test_exit_reason_values(self):
        assert ExitReason.STOP_HIT.value == "STOP_HIT"
        assert ExitReason.TARGET_HIT.value == "TARGET_HIT"
        assert ExitReason.MANUAL.value == "MANUAL"

    def test_agent_operational_state(self):
        assert AgentOperationalState.HALTED.value == "HALTED"
        assert AgentOperationalState.IDLE.value == "IDLE"

    def test_position_state_from_string(self):
        assert PositionState("POSITION_OPEN") is PositionState.POSITION_OPEN
        assert PositionState("CLOSED") is PositionState.CLOSED

    def test_all_states_unique(self):
        states = [s.value for s in PositionState]
        assert len(states) == len(set(states))


class TestTradingAgent:
    @pytest.fixture
    def mock_components(self):
        pm = MagicMock()
        pm.get_open_positions.return_value = []
        pm.get_daily_trade_count.return_value = 0
        es = MagicMock()
        cb = MagicMock()
        cb.allow_request.return_value = True
        db = MagicMock()
        notifier = MagicMock()
        settings = MagicMock()
        settings.agent = MagicMock()
        settings.agent.AGENT_ENABLED = True
        settings.agent.MAX_DAILY_TRADES = 10
        settings.agent.MAX_OPEN_POSITIONS = 5
        settings.agent.POSITION_MONITOR_ENABLED = False
        settings.agent.AGENT_MODE = "paper"
        settings.agent.EMERGENCY_CLOSE_ON_HALT = False
        settings.agent.AUDIT_LOG_ENABLED = False
        return pm, es, cb, db, notifier, settings

    def test_agent_disabled_skips(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        settings.agent.AGENT_ENABLED = False
        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        agent.on_scan_completed([])
        assert agent.state == AgentOperationalState.IDLE

    def test_agent_cant_trade_when_halted(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        agent.emergency_stop("test")
        assert not agent.can_trade()

    def test_emergency_stop_sets_halted(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        agent.emergency_stop("test")
        assert agent.state == AgentOperationalState.HALTED

    def test_pause_resume(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        agent.pause(0)
        assert agent.state == AgentOperationalState.PAUSED
        agent.resume()
        assert agent.state == AgentOperationalState.IDLE

    def test_status_returns_correct_structure(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        status = agent.status()
        assert "agent_state" in status
        assert "open_positions" in status
        assert "daily_trades" in status
        assert "positions" in status


class TestP0Regression:
    """BUG-1..BUG-6 regression tests (TDD red → green after fixes)."""

    @pytest.fixture
    def mock_components(self):
        pm = MagicMock()
        pm.get_open_positions.return_value = []
        pm.get_daily_trade_count.return_value = 0
        pm.get_position.return_value = None
        es = MagicMock()
        cb = MagicMock()
        cb.allow_request.return_value = True
        db = MagicMock()
        db.manager = MagicMock()
        db.manager.engine = MagicMock()
        notifier = MagicMock()
        settings = MagicMock()
        settings.agent = MagicMock()
        settings.agent.AGENT_ENABLED = True
        settings.agent.MAX_DAILY_TRADES = 10
        settings.agent.MAX_OPEN_POSITIONS = 5
        settings.agent.MIN_SCORE_THRESHOLD = 40
        settings.agent.MAX_HOLDING_DAYS = 3
        settings.agent.POSITION_MONITOR_ENABLED = False
        settings.agent.AGENT_MODE = "paper"
        settings.agent.EMERGENCY_CLOSE_ON_HALT = False
        settings.agent.AUDIT_LOG_ENABLED = False
        settings.agent.DAILY_REPORT_ENABLED = True
        settings.agent.TRAILING_STOP_ENABLED = False
        settings.agent.AGENT_LONG_ONLY = True
        settings.agent.AGENT_REQUIRE_FILL_BEFORE_POSITION = True
        return pm, es, cb, db, notifier, settings

    def test_rejected_order_does_not_open_position(self, mock_components):
        """BUG-1: Rejected broker order must NOT trigger open_position."""
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components

        # execute_signal returns None (rejected)
        es.execute_signal.return_value = None
        agent = TradingAgent(pm, es, cb, db, notifier, settings, execution_service=es)

        signal = MagicMock()
        signal.signal_type = MagicMock()
        signal.signal_type.__str__ = lambda self: "STRONG_BUY"
        signal.score = 50
        signal.ticker = "TEST.IS"
        signal.position_size = 100
        signal.price = 10.0
        signal.stop_loss = 9.0
        signal.target_price = 12.0

        agent._check_entries([signal])

        pm.open_position.assert_not_called()

    def test_rejected_attempt_with_accepted_false_no_position(self, mock_components):
        """BUG-1: ExecutionAttempt with accepted=False must NOT open_position."""
        from bist_bot.agent.trading_agent import TradingAgent
        from bist_bot.services.execution_service import ExecutionAttempt

        pm, es, cb, db, notifier, settings = mock_components

        es.execute_signal.return_value = ExecutionAttempt(
            ticker="TEST.IS",
            side="BUY",
            accepted=False,
            order_db_id=None,
            broker_order_id=None,
            state="REJECTED",
            error="broker_rejected",
        )
        agent = TradingAgent(pm, es, cb, db, notifier, settings, execution_service=es)

        signal = MagicMock()
        signal.signal_type = MagicMock()
        signal.signal_type.__str__ = lambda self: "STRONG_BUY"
        signal.score = 50
        signal.ticker = "TEST.IS"
        signal.position_size = 100
        signal.price = 10.0
        signal.stop_loss = 9.0
        signal.target_price = 12.0

        agent._check_entries([signal])
        pm.open_position.assert_not_called()

    def test_strong_sell_no_entry_no_long_open(self, mock_components):
        """BUG-2: STRONG_SELL must NOT trigger entry or open LONG position."""
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        settings.agent.AGENT_LONG_ONLY = True
        agent = TradingAgent(pm, es, cb, db, notifier, settings, execution_service=es)

        signal = MagicMock()
        signal.signal_type = MagicMock()
        signal.signal_type.__str__ = lambda self: "STRONG_SELL"
        signal.score = -50
        signal.ticker = "TEST.IS"
        signal.position_size = 100
        signal.price = 10.0

        agent._check_entries([signal])
        pm.open_position.assert_not_called()
        es.execute_signal.assert_not_called()

    def test_paper_mode_exit_success_calls_close_position(self, mock_components):
        """BUG-3: Paper mode exit success MUST call close_position."""
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        settings.agent.AGENT_MODE = "paper"
        pm.get_open_positions.return_value = [
            {
                "id": 1,
                "ticker": "TEST.IS",
                "entry_time": "2025-01-01T00:00:00+00:00",
                "entry_price": 10.0,
                "quantity": 100,
                "stop_loss": 9.0,
                "target_price": 12.0,
            }
        ]
        pm.check_exit_conditions.return_value = [
            {
                "position_id": 1,
                "ticker": "TEST.IS",
                "exit_reason": "STOP_HIT",
                "current_price": 8.0,
                "entry_price": 10.0,
                "quantity": 100,
                "pnl_pct": -20.0,
            }
        ]
        data_fetcher = MagicMock()
        data_fetcher.fetch_single.return_value = {"close": 8.0}

        agent = TradingAgent(pm, es, cb, db, notifier, settings, data_fetcher=data_fetcher)
        # Override _fetch_prices to return expected prices
        agent._fetch_prices = lambda tickers: {"TEST.IS": 8.0}
        es.exit_position.return_value = True

        agent._check_exits()

        pm.close_position.assert_called_once()

    def test_emergency_stop_uses_fetched_price(self, mock_components):
        """BUG-6: Emergency stop should use fetched market price, not entry_price."""
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        settings.agent.EMERGENCY_CLOSE_ON_HALT = True
        pm.get_open_positions.return_value = [
            {
                "id": 1,
                "ticker": "TEST.IS",
                "entry_price": 10.0,
                "quantity": 100,
            }
        ]
        data_fetcher = MagicMock()
        agent = TradingAgent(pm, es, cb, db, notifier, settings, data_fetcher=data_fetcher)
        # Override _fetch_prices to return expected prices
        agent._fetch_prices = lambda tickers: {"TEST.IS": 15.0}
        es.exit_position.return_value = True

        agent.emergency_stop("test")

        es.exit_position.assert_called_once()
        call_kwargs = es.exit_position.call_args
        assert call_kwargs.kwargs["current_price"] == 15.0

    def test_emergency_stop_no_price_skips_close(self, mock_components):
        """BUG-6: Emergency stop with no fetched price must NOT close at entry_price."""
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        settings.agent.EMERGENCY_CLOSE_ON_HALT = True
        pm.get_open_positions.return_value = [
            {
                "id": 1,
                "ticker": "TEST.IS",
                "entry_price": 10.0,
                "quantity": 100,
            }
        ]
        # No data_fetcher → _fetch_prices returns empty
        agent = TradingAgent(pm, es, cb, db, notifier, settings, data_fetcher=None)

        agent.emergency_stop("test")

        es.exit_position.assert_not_called()
        pm.close_position.assert_not_called()

    def test_entry_order_id_uses_attempt_real_id(self, mock_components):
        """BUG-1 side-effect: entry_order_id must come from ExecutionAttempt, not 0."""
        from bist_bot.agent.trading_agent import TradingAgent
        from bist_bot.services.execution_service import ExecutionAttempt

        pm, es, cb, db, notifier, settings = mock_components
        es.execute_signal.return_value = ExecutionAttempt(
            ticker="TEST.IS",
            side="BUY",
            accepted=True,
            order_db_id=42,
            broker_order_id="BRK-42",
            state="FILLED",
            fill_price=10.5,
        )
        agent = TradingAgent(pm, es, cb, db, notifier, settings, execution_service=es)

        signal = MagicMock()
        signal.signal_type = MagicMock()
        signal.signal_type.__str__ = lambda self: "STRONG_BUY"
        signal.score = 50
        signal.ticker = "TEST.IS"
        signal.position_size = 100
        signal.price = 10.0
        signal.stop_loss = 9.0
        signal.target_price = 12.0
        signal.kelly_fraction = 0

        agent._check_entries([signal])

        pm.open_position.assert_called_once()
        call_kwargs = pm.open_position.call_args
        assert call_kwargs.kwargs["entry_order_id"] == 42
        assert call_kwargs.kwargs["entry_price"] == 10.5

    def test_pause_cancels_previous_timer(self, mock_components):
        """P1: pause() should not leak daemon threads — old timer must be cancelled."""
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings)

        agent.pause(60)
        first_timer = agent._resume_timer
        assert first_timer is not None

        agent.resume()
        agent.pause(60)
        second_timer = agent._resume_timer
        assert second_timer is not None
        assert second_timer is not first_timer


class TestCommandHandler:
    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        agent.status.return_value = {
            "agent_state": "IDLE",
            "open_positions": 0,
            "max_open_positions": 5,
            "daily_trades": 0,
            "max_daily_trades": 10,
            "positions": [],
        }
        return agent

    def test_help_command(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        result = handler.handle("/help")
        assert "Komutları" in result or "help" in result.lower()

    def test_status_command(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        result = handler.handle("/status")
        assert "IDLE" in result

    def test_stop_command(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        result = handler.handle("/stop")
        mock_agent.emergency_stop.assert_called_once()
        assert "durduruldu" in result.lower()

    def test_pause_command(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        handler.handle("/pause 30")
        mock_agent.pause.assert_called_once_with(30)

    def test_resume_command(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        handler.handle("/resume")
        mock_agent.resume.assert_called_once()

    def test_unknown_command(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        result = handler.handle("/unknown_cmd")
        assert "Bilinmeyen" in result or "unknown" in result.lower()

    def test_close_without_ticker(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        result = handler.handle("/close")
        assert "Kullanım" in result or "usage" in result.lower()

    def test_close_unknown_ticker(self, mock_agent):
        from bist_bot.agent.command_handler import CommandHandler

        handler = CommandHandler(mock_agent)
        result = handler.handle("/close UNKNOWN.IS")
        assert "bulunamadı" in result.lower() or "not found" in result.lower()
