"""Pre-flight configuration validation tests.

These tests lock the fail-closed startup gates for dangerous or inconsistent
settings (risk caps, score thresholds, provider timeout budgets).
"""

from __future__ import annotations

import pytest

from bist_bot.config.settings import Settings, settings


def test_default_settings_pass_preflight() -> None:
    """Production defaults must always be considered safe to start."""
    errors = settings.collect_preflight_errors()
    assert errors == []
    settings.enforce_preflight_validation()  # must not raise


def test_max_position_cap_above_safe_limit_fails() -> None:
    cfg = settings.replace(MAX_POSITION_CAP_PCT=80.0)
    errors = cfg.collect_preflight_errors()
    assert any("MAX_POSITION_CAP_PCT" in err for err in errors)
    with pytest.raises(RuntimeError, match="Configuration Error:"):
        cfg.enforce_preflight_validation()


def test_max_total_risk_cannot_exceed_position_cap() -> None:
    cfg = settings.replace(MAX_POSITION_CAP_PCT=5.0, MAX_TOTAL_RISK_PCT=8.0)
    errors = cfg.collect_preflight_errors()
    assert any("MAX_TOTAL_RISK_PCT cannot exceed MAX_POSITION_CAP_PCT" in err for err in errors)


def test_initial_capital_must_be_positive() -> None:
    cfg = settings.replace(INITIAL_CAPITAL=0.0)
    errors = cfg.collect_preflight_errors()
    assert any("INITIAL_CAPITAL must be > 0" in err for err in errors)
    with pytest.raises(RuntimeError, match="Configuration Error:.*INITIAL_CAPITAL"):
        cfg.enforce_preflight_validation()


def test_score_threshold_ordering_is_enforced() -> None:
    cfg = settings.replace(
        STRONG_BUY_THRESHOLD=5,
        WEAK_BUY_THRESHOLD=8,
    )
    errors = cfg.collect_preflight_errors()
    assert any("Buy thresholds must satisfy" in err for err in errors)


def test_score_threshold_cannot_exceed_max_score_bound() -> None:
    cfg = settings.replace(STRONG_BUY_THRESHOLD=150)
    errors = cfg.collect_preflight_errors()
    assert any("STRONG_BUY_THRESHOLD cannot exceed max score bound" in err for err in errors)


def test_provider_batch_timeout_cannot_meet_or_exceed_streamlit_timeout() -> None:
    cfg = settings.replace(
        PROVIDER_BATCH_TIMEOUT_SECONDS=180,
        STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS=180,
    )
    errors = cfg.collect_preflight_errors()
    assert any("PROVIDER_BATCH_TIMEOUT_SECONDS must be <" in err for err in errors)
    with pytest.raises(RuntimeError, match="Configuration Error:.*PROVIDER_BATCH_TIMEOUT"):
        cfg.enforce_preflight_validation()


def test_official_timeout_cannot_exceed_streamlit_budget() -> None:
    cfg = settings.replace(
        OFFICIAL_TIMEOUT=200.0,
        STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS=180,
    )
    errors = cfg.collect_preflight_errors()
    assert any("OFFICIAL_TIMEOUT must be < STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS" in err for err in errors)


def test_scan_timeout_cannot_exceed_streamlit_budget() -> None:
    cfg = settings.replace(
        SCAN_TIMEOUT_SECONDS=200,
        STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS=180,
    )
    errors = cfg.collect_preflight_errors()
    assert any("SCAN_TIMEOUT_SECONDS must be <=" in err for err in errors)


def test_invalid_retry_count_fails() -> None:
    cfg = settings.replace(OFFICIAL_MAX_RETRIES=0, YFINANCE_MAX_RETRIES=9)
    errors = cfg.collect_preflight_errors()
    assert any("OFFICIAL_MAX_RETRIES" in err for err in errors)
    assert any("YFINANCE_MAX_RETRIES" in err for err in errors)


def test_indicator_period_inversions_fail() -> None:
    cfg = settings.replace(SMA_FAST=50, SMA_SLOW=20, RSI_OVERSOLD=80, RSI_OVERBOUGHT=30)
    errors = cfg.collect_preflight_errors()
    assert any("SMA_FAST must be < SMA_SLOW" in err for err in errors)
    assert any("RSI_OVERSOLD must be < RSI_OVERBOUGHT" in err for err in errors)


def test_validate_all_includes_preflight_errors() -> None:
    cfg = settings.replace(INITIAL_CAPITAL=-1.0, MAX_POSITION_CAP_PCT=99.0)
    all_errors = cfg.validate_all()
    assert any("INITIAL_CAPITAL" in err for err in all_errors)
    assert any("MAX_POSITION_CAP_PCT" in err for err in all_errors)


def test_enforce_preflight_message_prefix_is_stable() -> None:
    cfg = settings.replace(INITIAL_CAPITAL=-5.0)
    with pytest.raises(RuntimeError) as exc_info:
        cfg.enforce_preflight_validation()
    assert str(exc_info.value).startswith("Configuration Error:")


def test_fresh_settings_instance_defaults_are_valid() -> None:
    """A newly constructed Settings() with env defaults should pass preflight."""
    fresh = Settings()
    assert fresh.collect_preflight_errors() == []
