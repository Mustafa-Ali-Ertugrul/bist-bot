"""Test trading agent kuralları: skor filtresi, 3 gün kuralı, günlük rapor."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest


class TestScoreFilter:
    """Skor 40 altı hisseleri almamalı."""

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
        return pm, es, cb, db, notifier, settings

    def test_rejects_low_score_signals(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings)

        # Skor 30 olan sinyal (40'ın altında)
        signal = MagicMock()
        signal.signal_type = "STRONG_BUY"
        signal.score = 30
        signal.ticker = "TEST.IS"
        signal.position_size = 100
        signal.price = 10.0
        signal.stop_loss = 9.0
        signal.target_price = 12.0

        agent._check_entries([signal])

        # Pozisyon açılmamalı
        pm.open_position.assert_not_called()

    def test_accepts_high_score_signals(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        agent = TradingAgent(pm, es, cb, db, notifier, settings, execution_service=es)

        # Skor 50 olan sinyal (40'ın üstünde)
        signal = MagicMock()
        signal.signal_type = "STRONG_BUY"
        signal.score = 50
        signal.ticker = "TEST.IS"
        signal.position_size = 100
        signal.price = 10.0
        signal.stop_loss = 9.0
        signal.target_price = 12.0
        signal.regime = "TESTING"

        agent._check_entries([signal])

        # Pozisyon açılmalı
        pm.open_position.assert_called_once()


class TestHoldingDaysRule:
    """Bir hisse 3 günden fazla portföyde kalmamalı."""

    @pytest.fixture
    def mock_components(self):
        pm = MagicMock()
        es = MagicMock()
        cb = MagicMock()
        db = MagicMock()
        notifier = MagicMock()
        settings = MagicMock()
        settings.agent = MagicMock()
        settings.agent.AGENT_ENABLED = True
        settings.agent.MAX_HOLDING_DAYS = 3
        settings.agent.TRAILING_STOP_ENABLED = False
        settings.agent.AGENT_MODE = "paper"
        return pm, es, cb, db, notifier, settings

    def test_closes_after_3_days(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components

        # 4 gün önce açılan pozisyon
        old_entry_time = (datetime.now(UTC) - timedelta(days=4)).isoformat()
        pm.get_open_positions.return_value = [
            {
                "id": 1,
                "ticker": "TEST.IS",
                "entry_time": old_entry_time,
                "entry_price": 10.0,
                "quantity": 100,
                "stop_loss": 9.0,
                "target_price": 12.0,
            }
        ]

        # DataFrame with close/high/low so _fetch_exit_data can process it
        import pandas as pd

        df_mock = pd.DataFrame(
            {"close": [10.5, 10.4], "high": [10.6, 10.5], "low": [10.4, 10.3]},
            index=pd.to_datetime(["2026-08-26", "2026-08-27"]),
        )

        data_fetcher = MagicMock()
        data_fetcher.fetch_single.return_value = df_mock

        # Mock check_exit_conditions to return 3-day rule trigger
        pm.check_exit_conditions.return_value = [
            {
                "position_id": 1,
                "ticker": "TEST.IS",
                "exit_reason": "MAX_HOLDING_DAYS",
                "current_price": 10.5,
                "entry_price": 10.0,
                "quantity": 100,
                "days_held": 4,
            }
        ]

        agent = TradingAgent(pm, es, cb, db, notifier, settings, data_fetcher=data_fetcher)

        # Mock exit service
        es.exit_position.return_value = True

        agent._check_exits()

        # Exit çağrılmalı (3 gün kuralı nedeniyle)
        es.exit_position.assert_called()


class TestDailyReport:
    """Günlük rapor doğru çalışmalı."""

    @pytest.fixture
    def mock_components(self):
        pm = MagicMock()
        es = MagicMock()
        cb = MagicMock()
        db = MagicMock()
        notifier = MagicMock()
        settings = MagicMock()
        settings.agent = MagicMock()
        settings.agent.MAX_OPEN_POSITIONS = 5
        return pm, es, cb, db, notifier, settings

    def test_generates_report_with_positions(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components

        # 2 açık pozisyon
        entry_time = datetime.now(UTC).isoformat()
        pm.get_open_positions.return_value = [
            {
                "ticker": "TEST1.IS",
                "entry_time": entry_time,
                "entry_price": 10.0,
                "quantity": 100,
                "stop_loss": 9.0,
                "target_price": 12.0,
            },
            {
                "ticker": "TEST2.IS",
                "entry_time": entry_time,
                "entry_price": 20.0,
                "quantity": 50,
                "stop_loss": 18.0,
                "target_price": 24.0,
            },
        ]

        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        report = agent.daily_report()

        assert report["total_positions"] == 2
        assert report["max_positions"] == 5
        assert report["total_invested"] == 2000.0  # 10*100 + 20*50
        assert len(report["positions"]) == 2
        assert report["positions"][0]["ticker"] == "TEST1.IS"

    def test_generates_empty_report(self, mock_components):
        from bist_bot.agent.trading_agent import TradingAgent

        pm, es, cb, db, notifier, settings = mock_components
        pm.get_open_positions.return_value = []

        agent = TradingAgent(pm, es, cb, db, notifier, settings)
        report = agent.daily_report()

        assert report["total_positions"] == 0
        assert report["total_invested"] == 0.0
        assert report["positions"] == []
