"""AlgoLab broker skeleton tests with mocked HTTP flows only."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.execution.algolab_broker import (  # noqa: E402
    AlgoLabBroker,
    AlgoLabCredentials,
    AlgoLabEndpoints,
)
from bist_bot.execution.base import OrderSide, OrderType  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


def build_broker(session: requests.Session | None = None, dry_run: bool = True) -> AlgoLabBroker:
    return AlgoLabBroker(
        AlgoLabCredentials(api_key="api", username="user", password="pass", otp_code="123456"),
        endpoints=AlgoLabEndpoints(
            login="https://example.test/login",
            verify_otp="https://example.test/otp",
            positions="https://example.test/positions",
            account="https://example.test/account",
            orders="https://example.test/orders",
            order_status="https://example.test/order-status",
            cancel_order="https://example.test/cancel-order",
            open_orders="https://example.test/open-orders",
        ),
        session=session,
        dry_run=dry_run,
    )


def test_authenticate_flow_uses_login_and_otp() -> None:
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = [
        FakeResponse({"challenge_id": "challenge-1"}),
        FakeResponse({"session_token": "session-1", "encrypted_session": "enc-1"}),
    ]
    broker = build_broker(session=session, dry_run=True)

    assert broker.authenticate() is True
    assert session.request.call_count == 2


def test_place_order_dry_run_does_not_call_http() -> None:
    session = MagicMock(spec=requests.Session)
    broker = build_broker(session=session, dry_run=True)

    result = broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)

    assert result.accepted is True
    assert result.message.startswith("Dry-run")
    session.request.assert_not_called()


def test_request_retries_on_timeout_then_succeeds(monkeypatch) -> None:
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = [
        requests.Timeout("timeout"),
        requests.Timeout("timeout"),
        FakeResponse({"equity": 1, "cash_balance": 1, "buying_power": 1}),
    ]
    broker = build_broker(session=session, dry_run=False)
    broker._session_token = "token"
    broker._last_request_at = -1.0
    sleeps: list[float] = []
    monkeypatch.setattr(
        "bist_bot.execution.algolab_broker.time.sleep", lambda value: sleeps.append(value)
    )

    account = broker.get_account_info()

    assert account.equity == 1.0
    assert session.request.call_count == 3
    assert 0.5 in sleeps
    assert len(sleeps) >= 2


def test_rate_limit_waits_between_requests(monkeypatch) -> None:
    session = MagicMock(spec=requests.Session)
    session.request.return_value = FakeResponse({"equity": 1, "cash_balance": 1, "buying_power": 1})
    broker = build_broker(session=session, dry_run=False)
    broker._session_token = "token"
    broker._last_request_at = -1.0
    timeline = iter([0.0, 0.0, 0.1, 0.1])
    sleeps: list[float] = []
    monkeypatch.setattr("bist_bot.execution.algolab_broker.time.monotonic", lambda: next(timeline))
    monkeypatch.setattr(
        "bist_bot.execution.algolab_broker.time.sleep", lambda value: sleeps.append(round(value, 2))
    )

    broker.get_account_info()
    broker.get_account_info()

    assert sleeps[0] == 0.4
