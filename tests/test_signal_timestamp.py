"""H11: Signal timestamp naive/UTC mismatch regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from bist_bot.strategy.signal_models import Signal, SignalType, ensure_utc


class TestEnsureUtc:
    """ensure_utc converts aware datetimes to UTC; rejects naive ones."""

    def test_utc_aware_passes_through(self) -> None:
        dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        assert ensure_utc(dt) is dt

    def test_non_utc_aware_converts_to_utc(self) -> None:
        """A non-UTC aware datetime should be converted to UTC."""
        tr = timezone(timedelta(hours=3))
        dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=tr)
        result = ensure_utc(dt)
        assert result.tzinfo == UTC
        assert result == dt.astimezone(UTC)

    def test_naive_raises_value_error(self) -> None:
        naive = datetime(2025, 6, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Naive datetime"):
            ensure_utc(naive)


class TestSignalTimestampIsUtcAware:
    """Default signal timestamp must be UTC-aware."""

    def test_default_timestamp_is_utc_aware(self) -> None:
        signal = Signal(
            ticker="TEST.IS",
            signal_type=SignalType.BUY,
            score=50.0,
            price=100.0,
        )
        assert signal.timestamp.tzinfo is not None
        assert signal.timestamp.tzinfo == UTC

    def test_explicit_utc_timestamp_preserved(self) -> None:
        ts = datetime.now(UTC)
        signal = Signal(
            ticker="TEST.IS",
            signal_type=SignalType.BUY,
            score=50.0,
            price=100.0,
            timestamp=ts,
        )
        assert signal.timestamp == ts
        assert signal.timestamp.tzinfo == UTC


class TestTtlExpirationRegression:
    """H11 regression: 3-hour-old signal with 1h TTL must be expired."""

    def test_signal_expired_after_ttl(self) -> None:
        """Simulate now = production + 3h with TTL=1h → is_expired() == True."""
        produced = datetime.now(UTC) - timedelta(hours=3)
        signal = Signal(
            ticker="TEST.IS",
            signal_type=SignalType.BUY,
            score=50.0,
            price=100.0,
            timestamp=produced,
        )
        assert signal.is_expired() is True

    def test_signal_not_expired_within_ttl(self) -> None:
        produced = datetime.now(UTC) - timedelta(minutes=30)
        signal = Signal(
            ticker="TEST.IS",
            signal_type=SignalType.BUY,
            score=50.0,
            price=100.0,
            timestamp=produced,
        )
        assert signal.is_expired() is False


class TestNaiveTimestampRejected:
    """Silent replace(tzinfo=UTC) must not happen for naive datetimes."""

    def test_ensure_utc_rejects_naive_no_replace(self) -> None:
        """ensure_utc raises ValueError for naive datetime instead of relabeling."""
        naive = datetime(2025, 1, 1, 10, 0, 0)
        with pytest.raises(ValueError, match="Naive datetime"):
            ensure_utc(naive)

    def test_is_expired_rejects_naive_timestamp(self) -> None:
        """is_expired with a naive timestamp should raise, not silently relabel."""
        naive = datetime(2025, 1, 1, 10, 0, 0)
        # Direct construction sets a naive timestamp on the Signal
        # __post_init__ calls _make_expires_at which calls ensure_utc → raises
        with pytest.raises(ValueError, match="Naive datetime"):
            Signal(
                ticker="TEST.IS",
                signal_type=SignalType.BUY,
                score=50.0,
                price=100.0,
                timestamp=naive,
            )

    def test_replace_tzinfo_not_used_as_conversion(self) -> None:
        """Verify that ensure_utc does NOT silently use replace(tzinfo=UTC)."""
        naive = datetime(2025, 6, 1, 10, 0, 0)
        # The old buggy behavior: timestamp.replace(tzinfo=UTC) would make
        # 10:00 local → 10:00 UTC (wrong by offset hours).
        # ensure_utc must raise ValueError instead.
        with pytest.raises(ValueError):
            ensure_utc(naive)
        # Also verify that replace(tzinfo=UTC) would NOT give an error
        # (confirming the old bug was silent relabeling)
        silently_relabeled = naive.replace(tzinfo=UTC)
        assert silently_relabeled.tzinfo == UTC
        assert silently_relabeled.hour == 10  # same wall-clock hour, wrong offset
