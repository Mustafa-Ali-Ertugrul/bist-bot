"""Tests for signal model fixes and improvements."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from bist_bot.strategy.signal_models import Signal, SignalType, _make_expires_at
except ImportError:
    pytest.skip("Cannot import signal_models (missing dependencies)", allow_module_level=True)


class TestMakeExpiresAt:
    """Test the _make_expires_at function for proper timezone handling."""

    def test_aware_utc_timestamp_returns_utc_expires_at(self) -> None:
        """A UTC-aware timestamp should return an aware UTC expires_at."""
        aware_utc = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        result = _make_expires_at(aware_utc)

        assert result.tzinfo is not None
        assert result.tzinfo == UTC
        assert result == aware_utc + timedelta(minutes=60)

    def test_aware_non_utc_timestamp_converts_to_utc(self) -> None:
        """A non-UTC aware timestamp should be converted to UTC."""
        tr_tz = timezone(timedelta(hours=3))
        aware_tr = datetime(2025, 1, 1, 10, 0, 0, tzinfo=tr_tz)
        result = _make_expires_at(aware_tr)

        assert result.tzinfo is not None
        assert result.tzinfo == UTC
        assert result == aware_tr.astimezone(UTC) + timedelta(minutes=60)

    def test_naive_raises_value_error(self) -> None:
        """Naive timestamps are rejected instead of silently relabeled."""
        naive = datetime(2025, 1, 1, 10, 0, 0)
        with pytest.raises(ValueError, match="Naive datetime"):
            _make_expires_at(naive)

    def test_expiry_with_custom_ttl(self) -> None:
        """Verify TTL setting is respected."""
        aware_utc = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        result = _make_expires_at(aware_utc)
        # Default TTL is 60 minutes
        assert result - aware_utc == timedelta(minutes=60)


class TestSignalExpiration:
    """Test the Signal.is_expired() method with proper timezone handling."""

    def test_expired_aware_past_timestamp(self) -> None:
        """A signal with aware past timestamp should be expired."""
        past_aware = datetime(2020, 1, 1, 10, 0, 0, tzinfo=UTC)
        signal = Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=25.0,
            price=100.0,
            timestamp=past_aware,
        )
        now = datetime(2025, 1, 1, tzinfo=UTC)
        assert signal.is_expired(now=now) is True

    def test_not_expired_future_aware_timestamp(self) -> None:
        """A signal with future aware timestamp should not be expired."""
        future_aware = datetime(2030, 1, 1, 10, 0, 0, tzinfo=UTC)
        signal = Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=25.0,
            price=100.0,
            timestamp=future_aware,
        )
        now = datetime(2025, 1, 1, tzinfo=UTC)
        assert signal.is_expired(now=now) is False

    def test_default_expires_at_set_on_init(self) -> None:
        """Verify expires_at is set in __post_init__ when not provided."""
        signal = Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=25.0,
            price=100.0,
        )
        assert signal.expires_at is not None
        assert signal.expires_at > signal.timestamp.replace(tzinfo=UTC)


class TestSignalTypeFromValue:
    """Test SignalType.from_value() lookup logic."""

    def test_from_value_by_value(self) -> None:
        """Lookup by enum value should work."""
        assert SignalType.from_value("💰 GÜÇLÜ AL") == SignalType.STRONG_BUY
        assert SignalType.from_value("🟢 AL") == SignalType.BUY

    def test_from_value_by_enum_name(self) -> None:
        """Lookup by enum member name should work for persisted serialized values."""
        assert SignalType.from_value("STRONG_BUY") == SignalType.STRONG_BUY
        assert SignalType.from_value("BUY") == SignalType.BUY
        assert SignalType.from_value("strong_sell") == SignalType.STRONG_SELL

    def test_from_value_invalid_raises(self) -> None:
        """Invalid value should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown signal type"):
            SignalType.from_value("INVALID_VALUE")

    def test_signal_type_enum_members(self) -> None:
        """Verify all 8 signal types exist."""
        assert len(SignalType) == 8
        assert SignalType.STRONG_BUY in SignalType
        assert SignalType.BUY in SignalType
        assert SignalType.WEAK_BUY in SignalType
        assert SignalType.HOLD in SignalType
        assert SignalType.RADAR in SignalType
        assert SignalType.WEAK_SELL in SignalType
        assert SignalType.SELL in SignalType
        assert SignalType.STRONG_SELL in SignalType


class TestSignalDataclass:
    """Test the Signal dataclass structure and defaults."""

    def test_minimal_construction(self) -> None:
        """A Signal can be constructed with just ticker, type, score, and price."""
        sig = Signal(ticker="THYAO.IS", signal_type=SignalType.BUY, score=25.0, price=100.0)
        assert sig.ticker == "THYAO.IS"
        assert sig.signal_type == SignalType.BUY
        assert sig.score == 25.0
        assert sig.price == 100.0
        assert sig.reasons == []
        assert sig.stop_loss == 0.0
        assert sig.target_price == 0.0
        assert sig.position_size is None
        assert sig.signal_probability is None
        assert sig.kelly_fraction is None
        assert sig.confidence == "confidence.low"

    def test_full_construction(self) -> None:
        """A Signal with all fields populated should be valid."""
        ts = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        sig = Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.STRONG_BUY,
            score=75.0,
            price=100.0,
            reasons=["Momentum", "Volume"],
            stop_loss=95.0,
            target_price=110.0,
            position_size=10,
            signal_probability=0.85,
            kelly_fraction=0.15,
            timestamp=ts,
            confidence="confidence.high",
        )
        assert sig.reasons == ["Momentum", "Volume"]
        assert sig.stop_loss == 95.0
        assert sig.target_price == 110.0
        assert sig.position_size == 10
        assert sig.signal_probability == 0.85
        assert sig.kelly_fraction == 0.15
        assert sig.timestamp == ts
        assert sig.confidence == "confidence.high"
        # expires_at is set from UTC-aware timestamp
        assert sig.expires_at is not None
        assert sig.expires_at > ts

    def test_with_locale_returns_new_instance(self) -> None:
        """with_locale should return a new Signal with copied reasons."""
        original = Signal(
            ticker="THYAO.IS",
            signal_type=SignalType.BUY,
            score=25.0,
            price=100.0,
            reasons=["Reason A"],
        )
        copy = original.with_locale("en")
        assert copy is not original
        assert copy.ticker == original.ticker
        assert copy.reasons == original.reasons
        assert copy.reasons is not original.reasons  # Deep copy of list
