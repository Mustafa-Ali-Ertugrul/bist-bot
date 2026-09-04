from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from sqlalchemy.exc import IntegrityError

from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.execution.algolab_broker import (
    AlgoLabBroker,
    AlgoLabCredentials,
    AlgoLabEndpoints,
)
from bist_bot.execution.base import OrderSide, OrderState, OrderType


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


class _IntentStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.transitions: list[str] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        row = {**kwargs, "status": "pending", "active_key": kwargs["ticker"]}
        self.rows[str(kwargs["client_id"])] = row
        self.transitions.append("pending")
        return row

    def update(self, client_id: str, **kwargs: Any) -> dict[str, Any] | None:
        row = self.rows.get(client_id)
        if row is None:
            return None
        release_lock = kwargs.pop("release_lock", None)
        row.update(kwargs)
        if release_lock is True or (release_lock is None and row["status"] in {"ack", "rejected"}):
            row["active_key"] = None
        self.transitions.append(str(kwargs["status"]))
        return row

    def get_unresolved(self, ticker: str) -> dict[str, Any] | None:
        return next(
            (row for row in self.rows.values() if row["active_key"] == ticker),
            None,
        )


def _broker(
    session,
    intents: _IntentStore | None = None,
    *,
    send_client_id: bool = False,
) -> AlgoLabBroker:
    broker = AlgoLabBroker(
        AlgoLabCredentials(api_key="api", username="user", password="pass"),
        endpoints=AlgoLabEndpoints(
            orders="https://example.test/orders",
            open_orders="https://example.test/open-orders",
            order_history="https://example.test/order-history",
            cancel_order="https://example.test/cancel",
        ),
        session=session,
        dry_run=False,
        max_retries=3,
        max_requests_per_second=0,
        order_intents=intents,
        send_client_id=send_client_id,
    )
    broker._session_token = "token"
    return broker


def test_place_timeout_sends_once_then_reconciles_by_client_id() -> None:
    session = MagicMock(spec=requests.Session)
    intents = _IntentStore()
    captured: dict[str, str] = {}

    def request(method: str, url: str, **kwargs: Any):
        if method == "POST":
            captured["client_id"] = kwargs["json"]["client_order_id"]
            raise requests.Timeout("ambiguous timeout")
        return _Response(
            {
                "orders": [
                    {
                        "client_order_id": captured["client_id"],
                        "order_id": "broker-1",
                        "ticker": "THYAO.IS",
                        "side": "BUY",
                        "quantity": 10,
                        "order_type": "MARKET",
                        "state": "FILLED",
                    }
                ]
            }
        )

    session.request.side_effect = request
    broker = _broker(session, intents, send_client_id=True)

    result = broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)

    assert result.accepted is True
    assert result.order_id == captured["client_id"]
    assert result.broker_order_id == "broker-1"
    assert [call.args[0] for call in session.request.call_args_list].count("POST") == 1
    assert [call.args[0] for call in session.request.call_args_list].count("GET") == 1
    assert intents.transitions == ["pending", "sent", "unknown", "ack"]

    with pytest.raises(RuntimeError, match="unresolved intent"):
        broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)
    assert session.request.call_count == 2


def test_client_order_id_is_not_sent_until_contract_is_verified() -> None:
    session = MagicMock(spec=requests.Session)
    session.request.return_value = _Response(
        {"accepted": True, "order_id": "broker-1", "state": "SENT"}
    )
    broker = _broker(session)

    broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)

    assert "client_order_id" not in session.request.call_args.kwargs["json"]


def test_filled_order_is_reconciled_from_daily_history_without_client_id() -> None:
    session = MagicMock(spec=requests.Session)
    submitted_at = datetime.now(UTC).isoformat()
    session.request.side_effect = [
        requests.Timeout("ambiguous timeout"),
        _Response(
            {
                "orders": [
                    {
                        "order_id": "filled-1",
                        "ticker": "THYAO.IS",
                        "side": "BUY",
                        "quantity": 10,
                        "order_type": "MARKET",
                        "state": "FILLED",
                        "created_at": submitted_at,
                        "filled_quantity": 10,
                    }
                ]
            }
        ),
    ]
    intents = _IntentStore()
    broker = _broker(session, intents)

    result = broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)

    assert result.accepted is True
    assert result.state is OrderState.FILLED
    assert result.broker_order_id == "filled-1"
    assert intents.transitions == ["pending", "sent", "unknown", "ack"]
    with pytest.raises(RuntimeError, match="unresolved intent"):
        broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)


def test_place_401_refreshes_auth_and_retries_once(monkeypatch) -> None:
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = [
        _Response({}, status_code=401),
        _Response({"accepted": True, "order_id": "broker-2", "state": "SENT"}),
    ]
    intents = _IntentStore()
    broker = _broker(session, intents)
    monkeypatch.setattr(broker, "_auth_headers", lambda: {"Authorization": "Bearer refreshed"})

    result = broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)

    assert result.accepted is True
    assert session.request.call_count == 2
    assert intents.transitions == ["pending", "sent", "ack"]


def test_cancel_retries_and_treats_not_found_as_already_cancelled(monkeypatch) -> None:
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = [requests.Timeout("retry cancel"), _Response({}, status_code=404)]
    broker = _broker(session)
    monkeypatch.setattr("bist_bot.execution.algolab_broker.time.sleep", lambda _value: None)

    assert broker.cancel_order("broker-1") is True
    assert session.request.call_count == 2


def test_place_timeout_without_reconcile_match_remains_unknown(monkeypatch) -> None:
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = [requests.Timeout("ambiguous timeout"), _Response({"orders": []})]
    intents = _IntentStore()
    broker = _broker(session, intents)
    alert = MagicMock(return_value=True)
    monkeypatch.setattr("bist_bot.execution.algolab_broker.send_alert", alert)

    with pytest.raises(RuntimeError, match="outcome remains unknown"):
        broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)

    assert intents.transitions == ["pending", "sent", "unknown", "unknown"]
    assert intents.get_unresolved("THYAO.IS") is not None
    alert.assert_called_once()


def test_unresolved_intent_blocks_new_order_for_same_ticker() -> None:
    session = MagicMock(spec=requests.Session)
    intents = _IntentStore()
    intents.create(
        client_id="existing",
        ticker="THYAO.IS",
        side="BUY",
        quantity=10,
        order_type="MARKET",
        price=None,
        stop_price=None,
    )
    intents.update("existing", status="unknown")
    broker = _broker(session, intents)

    try:
        broker.place_order("THYAO.IS", OrderSide.BUY, 10, OrderType.MARKET)
    except RuntimeError as exc:
        assert "unresolved intent" in str(exc)
    else:  # pragma: no cover - safety assertion
        raise AssertionError("Expected unresolved intent to block a second order")
    session.request.assert_not_called()


def test_database_symbol_lock_releases_after_terminal_status(tmp_path) -> None:
    repository = DataAccess(DatabaseManager(sqlite_path=str(tmp_path / "intents.db"))).order_intents
    payload = {
        "ticker": "THYAO.IS",
        "side": "BUY",
        "quantity": 10,
        "order_type": "MARKET",
        "price": None,
        "stop_price": None,
    }
    repository.create(client_id="first", **payload)

    with pytest.raises(IntegrityError):
        repository.create(client_id="second", **payload)

    repository.update("first", status="ack")
    row = repository.create(client_id="second", **payload)
    assert row["status"] == "pending"
