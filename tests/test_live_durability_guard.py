from __future__ import annotations

import pytest

from bist_bot.config.settings import settings

_LIVE_ENDPOINTS = {
    "ALGOLAB_LOGIN_URL": "https://example.test/login",
    "ALGOLAB_VERIFY_OTP_URL": "https://example.test/otp",
    "ALGOLAB_ORDERS_URL": "https://example.test/orders",
    "ALGOLAB_ORDER_STATUS_URL": "https://example.test/order-status",
    "ALGOLAB_CANCEL_ORDER_URL": "https://example.test/cancel",
    "ALGOLAB_ORDER_HISTORY_URL": "https://example.test/order-history",
}


def _live_overrides() -> dict[str, object]:
    return {
        "BROKER_MODE": "paper",
        "BROKER_PROVIDER": "algolab",
        "ALGOLAB_API_KEY": "test-api-key",
        "ALGOLAB_USERNAME": "test-user",
        "ALGOLAB_PASSWORD": "test-password",
        "ALGOLAB_DRY_RUN": False,
        "CONFIRM_LIVE_TRADING": True,
        **_LIVE_ENDPOINTS,
    }


def test_live_algolab_rejects_missing_persistent_database_url() -> None:
    with settings.override(**_live_overrides(), DATABASE_URL="", DB_PATH="/tmp/orders.db"):
        with pytest.raises(RuntimeError, match="persistent non-SQLite DATABASE_URL"):
            settings.validate_broker_config()


def test_live_algolab_rejects_sqlite_database_url() -> None:
    with settings.override(
        **_live_overrides(),
        DATABASE_URL="sqlite:////var/lib/bist/orders.db",
        DB_PATH="/var/lib/bist/orders.db",
    ):
        with pytest.raises(RuntimeError, match="persistent non-SQLite DATABASE_URL"):
            settings.validate_broker_config()


def test_live_algolab_requires_reconciliation_endpoint() -> None:
    overrides = _live_overrides()
    overrides["ALGOLAB_ORDER_HISTORY_URL"] = ""
    with settings.override(**overrides, DATABASE_URL="postgresql://db/bist"):
        with pytest.raises(RuntimeError, match="ALGOLAB_ORDER_HISTORY_URL"):
            settings.validate_broker_config()


def test_live_algolab_accepts_persistent_database_and_endpoints() -> None:
    with settings.override(**_live_overrides(), DATABASE_URL="postgresql://db/bist"):
        settings.validate_broker_config()


def test_memory_rate_limit_warns_when_multiple_instances_expected() -> None:
    with settings.override(
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        EXPECTED_INSTANCE_COUNT=2,
        RATE_LIMIT_STORAGE_URI="memory://",
    ):
        with pytest.warns(RuntimeWarning, match="configure Redis"):
            settings.validate_broker_config()
