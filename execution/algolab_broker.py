"""AlgoLab execution provider skeleton.

Official public marketing pages confirm AlgoLab offers algorithmic trading, but the
current HTTP endpoint details are not published openly on the website pages available
to this repository. Endpoint paths therefore stay configurable and unresolved values
raise explicit TODO-style errors instead of guessing undocumented URLs.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

import requests

from execution.base import (
    AccountInfo,
    BaseExecutionProvider,
    Order,
    OrderResult,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlgoLabCredentials:
    api_key: str
    username: str
    password: str
    otp_code: str | None = None


@dataclass(frozen=True)
class AlgoLabEndpoints:
    login: str | None = None
    verify_otp: str | None = None
    positions: str | None = None
    account: str | None = None
    orders: str | None = None
    order_status: str | None = None
    cancel_order: str | None = None
    open_orders: str | None = None


class AlgoLabBroker(BaseExecutionProvider):
    """Configurable AlgoLab wrapper with dry-run safety and testable HTTP hooks."""

    def __init__(
        self,
        credentials: AlgoLabCredentials,
        *,
        endpoints: AlgoLabEndpoints | None = None,
        session: requests.Session | None = None,
        dry_run: bool = True,
        timeout: float = 10.0,
        max_retries: int = 3,
        max_requests_per_second: float = 2.0,
    ) -> None:
        self.credentials = credentials
        self.endpoints = endpoints or AlgoLabEndpoints()
        self.session = session or requests.Session()
        self.dry_run = dry_run
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_requests_per_second = max_requests_per_second
        self._auth_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0
        self._session_token: str | None = None
        self._session_encrypted: str | None = None

    def authenticate(self) -> bool:
        if self._session_token:
            return True
        if not self.endpoints.login or not self.endpoints.verify_otp:
            raise RuntimeError(
                "AlgoLab endpoint paths are not configured. TODO: set verified login and OTP endpoints before live use."
            )

        with self._auth_lock:
            if self._session_token:
                return True

            login_response = self._request(
                "POST",
                self.endpoints.login,
                auth_required=False,
                json={
                    "api_key": self.credentials.api_key,
                    "username": self.credentials.username,
                    "password": self.credentials.password,
                },
            )
            payload = login_response.json()
            otp_response = self._request(
                "POST",
                self.endpoints.verify_otp,
                auth_required=False,
                json={
                    "otp_code": self.credentials.otp_code,
                    "challenge_id": payload.get("challenge_id"),
                },
            )
            otp_payload = otp_response.json()
            self._session_token = str(otp_payload.get("session_token", "")) or None
            self._session_encrypted = str(otp_payload.get("encrypted_session", "")) or None
            return bool(self._session_token or self._session_encrypted)

    def get_positions(self) -> list[Position]:
        payload = self._json_request("GET", self._required_endpoint("positions"))
        positions = payload.get("positions", [])
        return [
            Position(
                ticker=str(item.get("ticker", "")),
                quantity=float(item.get("quantity", 0.0)),
                average_price=float(item.get("average_price", 0.0)),
                market_value=float(item.get("market_value", 0.0)),
                unrealized_pnl=float(item.get("unrealized_pnl", 0.0)),
            )
            for item in positions
        ]

    def get_account_info(self) -> AccountInfo:
        payload = self._json_request("GET", self._required_endpoint("account"))
        return AccountInfo(
            cash_balance=float(payload.get("cash_balance", 0.0)),
            buying_power=float(payload.get("buying_power", 0.0)),
            equity=float(payload.get("equity", 0.0)),
            currency=str(payload.get("currency", "TRY")),
            account_id=str(payload.get("account_id", "")) or None,
        )

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        if self.dry_run:
            logger.info("[DRY RUN] %s %s %.2f @ %s", side.value, ticker, quantity, order_type.value)
            return OrderResult(
                accepted=True,
                order_id=f"dryrun-{ticker}-{int(time.time() * 1000)}",
                state=OrderState.CREATED,
                message="Dry-run mode: order not sent.",
            )

        payload = self._json_request(
            "POST",
            self._required_endpoint("orders"),
            json={
                "ticker": ticker,
                "side": side.value,
                "quantity": quantity,
                "order_type": order_type.value,
                "price": price,
                "stop_price": stop_price,
            },
        )
        return OrderResult(
            accepted=bool(payload.get("accepted", True)),
            order_id=str(payload.get("client_order_id") or payload.get("order_id") or ""),
            broker_order_id=str(payload.get("order_id", "")) or None,
            state=OrderState(str(payload.get("state", OrderState.SENT.value)).upper()),
            message=str(payload.get("message", "")),
            raw_payload=payload,
        )

    def cancel_order(self, order_id: str) -> bool:
        payload = self._json_request("POST", self._required_endpoint("cancel_order"), json={"order_id": order_id})
        return bool(payload.get("cancelled", True))

    def get_order_status(self, order_id: str) -> OrderStatus:
        payload = self._json_request("GET", self._required_endpoint("order_status"), params={"order_id": order_id})
        return OrderStatus(
            order_id=str(payload.get("client_order_id") or order_id),
            broker_order_id=str(payload.get("order_id", "")) or None,
            state=OrderState(str(payload.get("state", OrderState.SENT.value)).upper()),
            filled_quantity=float(payload.get("filled_quantity", 0.0)),
            average_fill_price=float(payload.get("average_fill_price", 0.0)) or None,
            raw_payload=payload,
        )

    def get_open_orders(self) -> list[Order]:
        payload = self._json_request("GET", self._required_endpoint("open_orders"))
        orders = payload.get("orders", [])
        return [
            Order(
                ticker=str(item.get("ticker", "")),
                side=OrderSide(str(item.get("side", OrderSide.BUY.value)).upper()),
                quantity=float(item.get("quantity", 0.0)),
                order_type=OrderType(str(item.get("order_type", OrderType.MARKET.value)).upper()),
                price=float(item.get("price", 0.0)) or None,
                stop_price=float(item.get("stop_price", 0.0)) or None,
                order_id=str(item.get("client_order_id") or item.get("order_id") or ""),
                broker_order_id=str(item.get("order_id", "")) or None,
                state=OrderState(str(item.get("state", OrderState.SENT.value)).upper()),
                filled_quantity=float(item.get("filled_quantity", 0.0)),
                average_fill_price=float(item.get("average_fill_price", 0.0)) or None,
            )
            for item in orders
        ]

    def _required_endpoint(self, name: str) -> str:
        value = cast(str | None, getattr(self.endpoints, name))
        if not value:
            raise RuntimeError(f"AlgoLab endpoint '{name}' is not configured. TODO: verify official API path.")
        return value

    def _auth_headers(self) -> dict[str, str]:
        self.authenticate()
        headers = {"Accept": "application/json"}
        if self.credentials.api_key:
            headers["X-API-Key"] = self.credentials.api_key
        if self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"
        if self._session_encrypted:
            headers["X-Encrypted-Session"] = self._session_encrypted
        return headers

    def _throttle(self) -> None:
        if self.max_requests_per_second <= 0:
            return
        min_interval = 1.0 / self.max_requests_per_second
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_request_at = time.monotonic()

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        auth_required = kwargs.pop("auth_required", True)
        base_headers = kwargs.pop("headers", {})
        headers = {**base_headers, **self._auth_headers()} if auth_required else base_headers

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                self._throttle()
                response = self.session.request(method, url, headers=headers, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"AlgoLab request failed after {self.max_retries} attempts") from last_error

    def _json_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._request(method, url, **kwargs)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("AlgoLab response payload must be a JSON object")
        return payload
