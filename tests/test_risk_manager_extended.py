"""Extended tests for risk manager functionality."""

from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import patch

from bist_bot.risk_manager import RiskManager, RiskLevels


def build_test_df(rows=30, base_price=100.0, atr_value=2.0):
    """Helper to create test OHLCV dataframe with ATR."""
    data = []
    for i in range(rows):
        price = base_price + i * 0.1
        data.append({
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "atr": atr_value,
            "volume": 1000 + i * 10
        })
    return pd.DataFrame(data)


def test_risk_manager_initialization_with_settings(monkeypatch):
    """Test risk manager initialization uses settings when capital not provided."""
    # Mock settings
    class MockSettings:
        INITIAL_CAPITAL = 5000.0
    
    monkeypatch.setattr("bist_bot.risk.manager.settings", MockSettings())
    
    manager = RiskManager()  # No capital provided
    assert manager.capital == 5000.0


def test_risk_manager_initialization_with_zero_capital_raises():
    """Test that zero capital raises ValueError."""
    with pytest.raises(ValueError, match="capital must be greater than zero"):
        RiskManager(capital=0)


def test_calc_atr_levels_handles_missing_atr():
    """Test ATR levels calculation when ATR data is missing."""
    manager = RiskManager(capital=10000)
    df = build_test_df()
    # Remove ATR column
    df = df.drop(columns=["atr"])
    
    levels = manager._calc_atr_levels(df, 100.0, RiskLevels())
    # Should not crash and levels should remain default
    assert levels.stop_atr == 0.0
    assert levels.target_atr == 0.0


def test_calc_support_resistance_insufficient_data():
    """Test support/resistance calculation with insufficient data."""
    manager = RiskManager(capital=10000)
    df = build_test_df(rows=5)  # Less than minimum window of 10
    
    levels = manager._calc_support_resistance(df, 100.0, RiskLevels())
    # Should not crash and levels should remain default
    assert levels.stop_support == 0.0
    assert levels.target_resistance == 0.0


def test_calc_fibonacci_insufficient_data():
    """Test Fibonacci calculation with insufficient data."""
    manager = RiskManager(capital=10000)
    # Create dataframe with no price movement (diff <= 0)
    df = build_test_df(rows=5, base_price=100.0, atr_value=2.0)
    # Make all prices the same so swing_high == swing_low
    df["close"] = 100.0
    df["high"] = 100.0
    df["low"] = 100.0
    df["open"] = 100.0
    
    levels = manager._calc_fibonacci(df, 100.0, RiskLevels())
    # Should not crash and levels should remain default since diff <= 0
    assert levels.stop_fibonacci == 0.0
    assert levels.target_fibonacci == 0.0


def test_determine_final_levels_no_valid_stops():
    """Test final levels determination when no valid stops exist."""
    manager = RiskManager(capital=10000)
    levels = RiskLevels(
        stop_atr=150.0,  # Above price - invalid
        stop_support=150.0,  # Above price - invalid
        stop_fibonacci=150.0,  # Above price - invalid
        stop_percent=150.0,  # Above price - invalid
        stop_swing=150.0,  # Above price - invalid
        target_atr=50.0,  # Below price - invalid
        target_resistance=50.0,  # Below price - invalid
        target_fibonacci=50.0,  # Below price - invalid
        target_percent=50.0,  # Below price - invalid
        target_swing=50.0,  # Below price - invalid
    )
    
    result = manager._determine_final_levels(100.0, levels)
    # Should fall back to stop_percent even though it's invalid
    assert result.final_stop == 150.0


def test_calc_position_size_zero_risk_per_share():
    """Test position sizing when risk per share is zero or negative."""
    manager = RiskManager(capital=10000)
    
    # Test with zero risk per share (stop >= entry)
    levels = RiskLevels(final_stop=100.0, final_target=120.0)  # Equal to entry
    result = manager._calc_position_size(100.0, levels)
    assert result.position_size == 0
    assert result.max_loss_tl == 0
    
    # Test with negative risk per share (stop > entry)
    levels = RiskLevels(final_stop=110.0, final_target=120.0)  # Stop above entry
    result = manager._calc_position_size(100.0, levels)
    assert result.position_size == 0
    assert result.max_loss_tl == 0


def test_calc_position_size_respects_affordability_limit():
    """Test that position size respects maximum affordable shares."""
    manager = RiskManager(capital=10000)
    # Very small risk per share would normally give huge position
    levels = RiskLevels(
        final_stop=99.99,  # Very close to entry
        final_target=100.01,
        volatility_scale=1.0,
        correlation_scale=1.0
    )
    
    result = manager._calc_position_size(100.0, levels)
    # Should be limited by max_affordable = capital * 0.9 / price
    max_affordable = int(10000 * 0.9 / 100.0)  # 90 shares
    assert result.position_size <= max_affordable


def test_apply_position_budget_zero_risk_per_share():
    """Test position budget calculation with zero/negative risk per share."""
    manager = RiskManager(capital=10000)
    
    levels = RiskLevels(final_stop=100.0, final_target=120.0)  # Zero risk
    manager._apply_position_budget(100.0, levels)
    assert levels.position_size == 0
    assert levels.max_loss_tl == 0
    assert levels.risk_budget_tl == 0


def test_calculate_atr_pct_edge_cases():
    """Test ATR percentage calculation edge cases."""
    manager = RiskManager(capital=10000)
    
    # Test with zero price
    levels = RiskLevels(stop_atr=50.0)
    result = manager._calculate_atr_pct(levels, 0.0)
    assert result == 0.0
    
    # Test with zero stop price
    levels = RiskLevels(stop_atr=0.0)
    result = manager._calculate_atr_pct(levels, 100.0)
    assert result == 0.0


def test_calculate_risk_throttle_edge_cases():
    """Test risk throttle calculation edge cases."""
    manager = RiskManager(capital=10000)
    # Set baseline to known value for predictable testing
    manager.atr_baseline_pct = 0.025
    manager.atr_min_risk_scale = 0.35
    
    # Test zero ATR pct
    result = manager._calculate_risk_throttle(0.0)
    assert result == 1.0
    
    # Test ATR pct at baseline
    result = manager._calculate_risk_throttle(0.025)
    assert result == 1.0
    
    # Test very high ATR pct (should hit min scale)
    result = manager._calculate_risk_throttle(1.0)  # Very high
    assert result == 0.35  # Should be at minimum
    
    # Test moderate ATR pct
    result = manager._calculate_risk_throttle(0.05)  # Double baseline
    assert result == 0.5  # Between baseline and 1.0


def test_get_correlated_positions_uses_global_cache():
    """Test that correlated positions uses global correlation cache when available."""
    manager = RiskManager(capital=10000)
    manager.correlation_threshold = 0.5
    
    # Setup portfolio history
    df1 = build_test_df()
    df2 = build_test_df(base_price=200.0)
    manager._portfolio_history = {
        "TICKER1.IS": df1,
        "TICKER2.IS": df2
    }
    
    # Setup mock global correlation cache
    mock_corr = pd.DataFrame(
        [[1.0, 0.8], [0.8, 1.0]],
        index=["TICKER3.IS", "TICKER1.IS"],
        columns=["TICKER3.IS", "TICKER1.IS"]
    )
    manager._global_corr_cache = mock_corr
    
    # Test with TICKER3.IS - should find correlation with TICKER1.IS
    candidate_df = build_test_df(base_price=150.0)
    correlated = manager._get_correlated_positions("TICKER3.IS", candidate_df)
    assert "TICKER1.IS" in correlated
    
    # Test with Ticker not in cache
    manager._global_corr_cache = None
    correlated = manager._get_correlated_positions("UNKNOWN.IS", candidate_df)
    # Should fall back to direct calculation
    assert isinstance(correlated, list)


def test_sector_limit_functionality():
    """Test sector limit checking functionality."""
    manager = RiskManager(capital=10000)
    
    # Mock sector settings
    class MockSettings:
        SECTOR_MAP = {"THYAO.IS": "Havaçılık", "ASELS.IS": "Savunma"}
        SECTOR_LIMIT = 1
    
    with patch("bist_bot.risk.manager.settings", MockSettings()):
        # First check should pass
        assert manager.check_sector_limit("THYAO.IS") is True
        
        # Second check for same sector should fail
        assert manager.check_sector_limit("THYAO.IS") is False  # Same ticker again
        
        # Different sector should pass
        assert manager.check_sector_limit("ASELS.IS") is True
        
        # Second check for defense sector should fail
        assert manager.check_sector_limit("ASELS.IS") is False
        
        # Reset and try again
        manager.reset_sectors()
        assert manager.check_sector_limit("THYAO.IS") is True


def test_sector_scan_context_manager():
    """Test sector scan context manager resets sectors."""
    manager = RiskManager(capital=10000)
    
    class MockSettings:
        SECTOR_MAP = {"THYAO.IS": "Test"}
        SECTOR_LIMIT = 1
    
    with patch("bist_bot.risk.manager.settings", MockSettings()):
        # Use one sector slot
        manager.check_sector_limit("THYAO.IS")
        
        # Context manager should reset
        with manager.sector_scan():
            # Should be able to use sector again inside context
            assert manager.check_sector_limit("THYAO.IS") is True
            
        # After context, should be reset
        assert manager.check_sector_limit("THYAO.IS") is True


def test_build_global_correlation_cache():
    """Test building global correlation cache from data dictionary."""
    manager = RiskManager(capital=10000)
    
    # Create test data
    df1 = build_test_df(rows=20)
    df2 = build_test_df(rows=20, base_price=200.0)
    df3 = build_test_df(rows=20, base_price=300.0)
    
    # Test data in the format expected by the method
    data = {
        "TICKER1.IS": {"trend": df1},
        "TICKER2.IS": df2,  # Direct dataframe
        "TICKER3.IS": {"trend": df3}
    }
    
    manager.build_global_correlation_cache(data)
    
    # Should have created cache
    assert manager._global_corr_cache is not None
    assert isinstance(manager._global_corr_cache, pd.DataFrame)
    # Should have 3 tickers
    assert manager._global_corr_cache.shape == (3, 3)
    
    # Test with insufficient data
    manager2 = RiskManager(capital=10000)
    empty_data = {"TICKER1.IS": None}
    manager2.build_global_correlation_cache(empty_data)
    assert manager2._global_corr_cache is None


def test_risk_levels_dataclass_defaults():
    """Test that RiskLevels dataclass has correct default values."""
    levels = RiskLevels()
    
    # Check numeric defaults
    assert levels.stop_atr == 0.0
    assert levels.target_atr == 0.0
    assert levels.final_stop == 0.0
    assert levels.final_target == 0.0
    assert levels.position_size == 0
    assert levels.volatility_scale == 1.0
    assert levels.correlation_scale == 1.0
    assert levels.blocked_by_correlation is False
    
    # Check list defaults
    assert levels.correlated_tickers == []
    
    # Check string defaults
    assert levels.method_used == ""
    assert levels.confidence == "DÜŞÜK"


def test_risk_manager_with_custom_parameters():
    """Test risk manager initialization with custom parameters."""
    manager = RiskManager(
        capital=50000,
        max_risk_per_trade_pct=5.0,
        atr_stop_multiplier=3.0,
        atr_target_multiplier=5.0,
        fixed_stop_pct=10.0,
        fixed_target_pct=15.0
    )
    
    assert manager.capital == 50000
    assert manager.max_risk_pct == 5.0
    assert manager.atr_stop_mult == 3.0
    assert manager.atr_target_mult == 5.0
    assert manager.fixed_stop_pct == 10.0
    assert manager.fixed_target_pct == 15.0
