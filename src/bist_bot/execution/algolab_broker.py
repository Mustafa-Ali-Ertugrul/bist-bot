"""AlgoLab execution provider.

Configurable wrapper for the AlgoLab algorithmic trading API.  Endpoint paths are
fully configurable because the official HTTP routes are not publicly documented;
unresolved values raise explicit errors instead of guessing undocumented URLs.

Features:
  - Two-step authentication (login + OTP) with thread-safe caching
  - Exponential-backoff retries with jitter
  - Token-based circuit breaker that trips after consecutive failures
  - Request-scoped timeouts (connect / read split)
  - Dry-run safety for order placement
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any, Protocol, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

from bist_bot.app_logging import get_logger
from bist_bot.app_metrics import inc_counter, set_gauge
from bist_bot.config.settings import settings
from bist_bot.execution.base import (
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
from bist_bot.observability.alerts import AlertLevel, send_alert

logger = get_logger(__name__, component="algolab_broker")
TRADING_TIMEZONE = ZoneInfo("Europe/Istanbul")


class OrderIntentsProtocol(Protocol):
    def create(self, **kwargs: Any) -> dict[str, Any]: ...

    def update(self, client_id: str, **kwargs: Any) -> dict[str, Any] | None: ...

    def get_unresolved(self, ticker: str) -> dict[str, Any] | None: ...

    def list_reconcilable(self) -> list[dict[str, Any]]: ...

    def is_broker_order_bound(self, broker_order_id: str, *, exclude_client_id: str) -> bool: ...


class _CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    _state: _CircuitState = field(default=_CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_at: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def state(self) -> _CircuitState:
        with self._lock:
            if self._state is _CircuitState.OPEN:
                if time.monotonic() - self._last_failure_at >= self.recovery_timeout:
                    self._state = _CircuitState.HALF_OPEN
            return self._state

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = _CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_at = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = _CircuitState.OPEN
                logger.warning("circuit_breaker_open", consecutive_failures=self._failure_count)

    def allow_request(self) -> bool:
        return self.state in {_CircuitState.CLOSED, _CircuitState.HALF_OPEN}


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
    order_history: str | None = None


class AlgoLabBroker(BaseExecutionProvider):
    """Configurable AlgoLab wrapper with dry-run safety, circuit breaker, and retries."""

    def __init__(
        self,
        credentials: AlgoLabCredentials,
        *,
        endpoints: AlgoLabEndpoints | None = None,
        session: requests.Session | None = None,
        dry_run: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_retries: int = 3,
        max_requests_per_second: float = 2.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        order_intents: OrderIntentsProtocol | None = None,
        send_client_id: bool = False,
        reconcile_window_seconds: int = 180,
        clock: Callable[[], datetime] | None = None,
        accounting_service: Any | None = None,
        status_map: dict[str, str] | None = None,
        cancel_remainder: bool = True,
    ) -> None:
        self.credentials = credentials
        self.endpoints = endpoints or AlgoLabEndpoints()
        self.session = session or requests.Session()
        self.dry_run = dry_run
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.timeout: tuple[float, float] = (self.connect_timeout, self.read_timeout)
        self.max_retries = max_retries
        self.max_requests_per_second = max_requests_per_second
        self._circuit = _CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
        )
        self._auth_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0
        self._session_token: str | None = None
        self._session_encrypted: str | None = None
        self.order_intents = order_intents
        self.send_client_id = send_client_id
        self.reconcile_window_seconds = max(1, reconcile_window_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self.accounting_service = accounting_service
        self.cancel_remainder = cancel_remainder
        self._status_map = self._resolve_status_map(status_map)

    def authenticate(self) -> bool:
        if self._session_token:
            return True
        if not self.endpoints.login or not self.endpoints.verify_otp:
            raise NotImplementedError(
                "AlgoLab login/OTP endpoints are not yet configured for live trading. "
                "Please configure the broker endpoints before enabling live trading."
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
        *,
        order_db_id: int | None = None,
        signal_snapshot: str | None = None,
    ) -> OrderResult:
        client_id = uuid4().hex
        submitted_at = self._normalize_datetime(self._clock())
        if self.order_intents is not None:
            unresolved = self.order_intents.get_unresolved(ticker)
            if unresolved is not None:
                raise RuntimeError(
                    "Order submission blocked: unresolved intent "
                    f"{unresolved['client_id']} exists for {ticker}"
                )
            self.order_intents.create(
                client_id=client_id,
                ticker=ticker,
                side=side.value,
                quantity=quantity,
                order_type=order_type.value,
                price=price,
                stop_price=stop_price,
                order_db_id=order_db_id,
                signal_snapshot=signal_snapshot,
            )
        if self.dry_run:
            logger.info(
                "dry_run_order",
                side=side.value,
                ticker=ticker,
                quantity=quantity,
                order_type=order_type.value,
            )
            result = OrderResult(
                accepted=True,
                order_id=client_id,
                state=OrderState.CREATED,
                message="Dry-run mode: order not sent.",
            )
            if self.order_intents is not None:
                self.order_intents.update(client_id, status="ack", detail="dry-run")
            return result

        if self.order_intents is not None:
            self.order_intents.update(client_id, status="sent")
        order_payload: dict[str, Any] = {
            "ticker": ticker,
            "side": side.value,
            "quantity": quantity,
            "order_type": order_type.value,
            "price": price,
            "stop_price": stop_price,
        }
        if self.send_client_id:
            order_payload["client_order_id"] = client_id
        try:
            payload = self._json_request(
                "POST",
                self._required_endpoint("orders"),
                retry_mode="place",
                json=order_payload,
            )
        except requests.RequestException as exc:
            if self.order_intents is not None:
                self.order_intents.update(
                    client_id,
                    status="unknown",
                    detail=f"{type(exc).__name__}: submission outcome unknown",
                )
            return self._reconcile_order(
                client_id=client_id,
                ticker=ticker,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                stop_price=stop_price,
                submitted_at=submitted_at,
            )

        accepted = bool(payload.get("accepted", True))
        broker_order_id = str(payload.get("order_id", "")) or None
        if self.order_intents is not None:
            self.order_intents.update(
                client_id,
                status="ack" if accepted else "rejected",
                broker_order_id=broker_order_id,
                detail=str(payload.get("message", "")) or None,
            )
        return OrderResult(
            accepted=accepted,
            order_id=str(payload.get("client_order_id") or client_id),
            broker_order_id=broker_order_id,
            state=OrderState(str(payload.get("state", OrderState.SENT.value)).upper()),
            message=str(payload.get("message", "")),
            raw_payload=payload,
        )

    def cancel_order(self, order_id: str) -> bool:
        response = self._request(
            "POST",
            self._required_endpoint("cancel_order"),
            retry_mode="cancel",
            json={"order_id": order_id},
        )
        if response.status_code == 404:
            return True
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("AlgoLab response payload must be a JSON object")
        return bool(payload.get("cancelled", True))

    def _reconcile_order(
        self,
        *,
        client_id: str,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None,
        stop_price: float | None,
        submitted_at: datetime,
    ) -> OrderResult:
        try:
            window = timedelta(seconds=self.reconcile_window_seconds)
            trading_days = sorted(
                {
                    (submitted_at - window).astimezone(TRADING_TIMEZONE).date(),
                    submitted_at.astimezone(TRADING_TIMEZONE).date(),
                    (submitted_at + window).astimezone(TRADING_TIMEZONE).date(),
                }
            )
            daily_orders = [
                order
                for trading_day in trading_days
                for order in self.get_daily_orders(trading_day)
            ]
        except Exception as exc:
            if self.order_intents is not None:
                self.order_intents.update(
                    client_id,
                    status="unknown",
                    detail=f"reconcile failed: {type(exc).__name__}",
                )
            self._alert_reconcile_required(
                client_id=client_id,
                ticker=ticker,
                reason=f"daily order history unavailable: {type(exc).__name__}",
            )
            raise RuntimeError(
                f"Order {client_id} outcome is unknown; reconciliation failed"
            ) from exc

        eligible_orders = [
            order
            for order in daily_orders
            if not (
                order.broker_order_id
                and self.order_intents is not None
                and self.order_intents.is_broker_order_bound(
                    order.broker_order_id,
                    exclude_client_id=client_id,
                )
            )
        ]
        id_matches = (
            [
                order
                for order in eligible_orders
                if order.metadata.get("client_order_id") == client_id
            ]
            if self.send_client_id
            else []
        )
        matches = id_matches or [
            order
            for order in eligible_orders
            if order.ticker == ticker
            and order.side == side
            and order.order_type == order_type
            and abs(order.quantity - quantity) < 1e-9
            and self._same_optional_number(order.price, price)
            and self._same_optional_number(order.stop_price, stop_price)
            and abs((order.created_at - submitted_at).total_seconds())
            <= self.reconcile_window_seconds
        ]
        if len(matches) == 1:
            match = matches[0]
            if match.metadata.get("state_known") is False:
                return self._keep_reconcile_unknown(
                    client_id=client_id,
                    ticker=ticker,
                    reason=f"unknown broker order state: {match.metadata.get('raw_state')}",
                )

            filled_qty = float(getattr(match, "filled_quantity", 0.0) or 0.0)
            avg_price = getattr(match, "average_fill_price", None)
            broker_order_id = match.broker_order_id or match.order_id

            # Case 1: zero filled quantity
            if filled_qty <= 0:
                if match.state in {OrderState.CANCELLED, OrderState.REJECTED}:
                    if self.order_intents is not None:
                        self.order_intents.update(
                            client_id,
                            status="rejected",
                            broker_order_id=broker_order_id,
                            detail=f"broker history state={match.state.value}, filled=0",
                            release_lock=True,
                        )
                    return OrderResult(
                        accepted=False,
                        order_id=client_id,
                        broker_order_id=broker_order_id,
                        state=match.state,
                        message="Broker history confirms order cancelled/rejected with zero fills.",
                    )
                # Still OPEN with zero fills: cancel remainder if enabled
                if self.cancel_remainder and match.broker_order_id:
                    try:
                        self.cancel_order(str(match.broker_order_id))
                        if self.order_intents is not None:
                            self.order_intents.update(
                                client_id,
                                status="rejected",
                                broker_order_id=broker_order_id,
                                detail="cancelled unfilled remainder",
                                release_lock=True,
                            )
                        return OrderResult(
                            accepted=False,
                            order_id=client_id,
                            broker_order_id=broker_order_id,
                            state=OrderState.CANCELLED,
                            message="Unfilled open remainder cancelled during reconciliation.",
                        )
                    except Exception as exc:
                        logger.warning("reconcile_cancel_remainder_failed", error=str(exc))
                        return self._keep_reconcile_unknown(
                            client_id=client_id,
                            ticker=ticker,
                            reason="unfilled order could not be cancelled",
                        )
                # Cannot cancel remainder or cancel not requested
                return self._keep_reconcile_unknown(
                    client_id=client_id,
                    ticker=ticker,
                    reason="order remains open with zero fills",
                )

            # Case 2: filled_qty > 0 (applies even if state is CANCELLED/PARTIAL/FILLED)
            # If partial fill and still open, cancel remainder if enabled
            if (
                self.cancel_remainder
                and match.state in {OrderState.SENT, OrderState.CREATED}
                and match.broker_order_id
            ):
                try:
                    self.cancel_order(str(match.broker_order_id))
                except Exception as exc:
                    logger.warning("reconcile_cancel_partial_remainder_failed", error=str(exc))
                    inc_counter("order_intents_unaccounted_total")
                    if self.order_intents is not None:
                        self.order_intents.update(
                            client_id,
                            status="ack_unaccounted",
                            broker_order_id=broker_order_id,
                            detail="partial fill confirmed but remainder cancel failed",
                            release_lock=False,
                        )
                    self._alert_reconcile_required(
                        client_id=client_id,
                        ticker=ticker,
                        reason="partial fill confirmed but remainder cancel failed",
                    )
                    return OrderResult(
                        accepted=True,
                        order_id=client_id,
                        broker_order_id=broker_order_id,
                        state=match.state,
                        message="Partial fill confirmed; remainder cancel failed.",
                    )

            # Accounting integration
            final_status = "ack"
            final_detail = "reconciled from daily order history"
            if self.accounting_service is not None and self.order_intents is not None:
                intent_row = self.order_intents.get(client_id) or {}
                outcome = self.accounting_service.record_fill(
                    intent=intent_row,
                    broker_order_id=broker_order_id,
                    filled_qty=filled_qty,
                    avg_fill_price=avg_price,
                    broker_state=match.state.value,
                )
                final_status = outcome.status
                final_detail = outcome.detail
                if not outcome.success:
                    self._alert_reconcile_required(
                        client_id=client_id,
                        ticker=ticker,
                        reason=f"reconcile accounting outcome: {final_status} ({final_detail})",
                    )

            if self.order_intents is not None:
                # Compare-and-set: update only if still in pre-reconcile status
                self.order_intents.update_conditional(
                    client_id,
                    status=final_status,
                    expected_statuses=("pending", "sent", "unknown"),
                    broker_order_id=broker_order_id,
                    detail=final_detail,
                    release_lock=False,  # Lock remains until manual admin verification
                )

            return OrderResult(
                accepted=True,
                order_id=client_id,
                broker_order_id=broker_order_id,
                state=match.state,
                message=f"Order reconciled ({final_status}): {final_detail}",
            )
        if not matches:
            return self._keep_reconcile_unknown(
                client_id=client_id,
                ticker=ticker,
                reason="no matching order in daily order history",
            )

        if self.order_intents is not None:
            self.order_intents.update(
                client_id,
                status="unknown",
                detail=f"ambiguous reconciliation: {len(matches)} matches",
            )
        self._alert_reconcile_required(
            client_id=client_id,
            ticker=ticker,
            reason=f"ambiguous daily history match count: {len(matches)}",
        )
        raise RuntimeError(
            f"Order {client_id} outcome remains unknown; {len(matches)} broker matches found"
        )

    def _keep_reconcile_unknown(
        self,
        *,
        client_id: str,
        ticker: str,
        reason: str,
    ) -> OrderResult:
        if self.order_intents is not None:
            self.order_intents.update(
                client_id,
                status="unknown",
                detail=f"{reason}; manual resolution required",
                release_lock=False,
            )
        self._alert_reconcile_required(client_id=client_id, ticker=ticker, reason=reason)
        raise RuntimeError(f"Order {client_id} outcome remains unknown; {reason}")

    def reconcile_pending_intents(self, *, background: bool = False) -> dict[str, int]:
        if background:
            t = threading.Thread(
                target=self._run_reconcile_pending_intents,
                name="algolab-startup-reconcile",
                daemon=True,
            )
            t.start()
            return {"attempted": 0, "resolved": 0, "unknown": 0}
        return self._run_reconcile_pending_intents()

    def _run_reconcile_pending_intents(self) -> dict[str, int]:
        summary = {"attempted": 0, "resolved": 0, "unknown": 0}
        if self.order_intents is None:
            set_gauge("reconcile_startup_pending", 0.0)
            return summary
        try:
            intents = self.order_intents.list_reconcilable()
        except Exception:
            set_gauge("reconcile_startup_pending", 0.0)
            raise

        pending_count = float(len(intents))
        set_gauge("reconcile_startup_pending", pending_count)
        for intent in intents:
            summary["attempted"] += 1
            created_at = self._normalize_datetime(intent["created_at"])
            try:
                self._reconcile_order(
                    client_id=str(intent["client_id"]),
                    ticker=str(intent["ticker"]),
                    side=OrderSide(str(intent["side"])),
                    quantity=float(intent["quantity"]),
                    order_type=OrderType(str(intent["order_type"])),
                    price=float(intent["price"]) if intent["price"] is not None else None,
                    stop_price=(
                        float(intent["stop_price"]) if intent["stop_price"] is not None else None
                    ),
                    submitted_at=created_at,
                )
            except (RuntimeError, requests.RequestException):
                summary["unknown"] += 1
            else:
                summary["resolved"] += 1
            finally:
                pending_count = max(0.0, pending_count - 1.0)
                set_gauge("reconcile_startup_pending", pending_count)
        set_gauge("reconcile_startup_pending", 0.0)
        logger.info("startup_order_reconciliation_completed", **summary)
        return summary

    @staticmethod
    def _same_optional_number(left: float | None, right: float | None) -> bool:
        if left is None or right is None:
            return left is right
        return abs(left - right) < 1e-9

    def get_order_status(self, order_id: str) -> OrderStatus:
        payload = self._json_request(
            "GET", self._required_endpoint("order_status"), params={"order_id": order_id}
        )
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
        return self._parse_orders(payload)

    def get_daily_orders(self, trading_day: date) -> list[Order]:
        payload = self._json_request(
            "GET",
            self._required_endpoint("order_history"),
            params={"date": trading_day.isoformat()},
        )
        return self._parse_orders(payload)

    def _parse_orders(self, payload: dict[str, Any]) -> list[Order]:
        orders = payload.get("orders", [])
        if not isinstance(orders, list):
            raise ValueError("AlgoLab orders payload must contain a list")
        return [self._parse_order(item) for item in orders if isinstance(item, dict)]

    _UNMAPPED_RAW_SEEN: set[str] = set()

    @classmethod
    def _record_unmapped_status(cls, raw_state: str) -> None:
        inc_counter("unmapped_broker_status_total")
        normalized = raw_state.strip().upper()
        if len(cls._UNMAPPED_RAW_SEEN) < 20:
            cls._UNMAPPED_RAW_SEEN.add(normalized)
            label = normalized
        else:
            label = normalized if normalized in cls._UNMAPPED_RAW_SEEN else "OTHER"
        logger.warning("unmapped_broker_status", raw_state=raw_state, metric_label=label)

    def _resolve_status_map(self, explicit_map: dict[str, str] | None) -> dict[str, str]:
        if explicit_map is not None:
            return {k.strip().upper(): v.strip().upper() for k, v in explicit_map.items()}
        raw_env = getattr(settings, "ALGOLAB_STATUS_MAP", "") or ""
        if raw_env.strip():
            import json as _json

            try:
                data = _json.loads(raw_env)
                if isinstance(data, dict):
                    return {str(k).strip().upper(): str(v).strip().upper() for k, v in data.items()}
            except Exception:
                logger.warning("algolab_status_map_parse_failed", raw=raw_env)
        return {}

    def _parse_order(self, item: dict[str, Any]) -> Order:
        raw_timestamp = item.get("created_at") or item.get("timestamp") or item.get("order_time")
        created_at = datetime.min.replace(tzinfo=UTC)
        if raw_timestamp:
            try:
                created_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                else:
                    created_at = created_at.astimezone(UTC)
            except ValueError:
                created_at = datetime.min.replace(tzinfo=UTC)
        state_text = str(item.get("state", OrderState.SENT.value)).upper()
        state_aliases = {"EXECUTED": "FILLED", "COMPLETED": "FILLED", "CANCELED": "CANCELLED"}
        # Check custom status map first, then built-in aliases
        if state_text in self._status_map:
            normalized_state = self._status_map[state_text]
        else:
            normalized_state = state_aliases.get(state_text, state_text)
        try:
            state = OrderState(normalized_state)
            state_known = True
        except ValueError:
            state = OrderState.CREATED
            state_known = False
            self._record_unmapped_status(state_text)
        client_order_id = str(item.get("client_order_id", "")) or None
        broker_order_id = str(item.get("order_id", "")) or None
        return Order(
            ticker=str(item.get("ticker", "")),
            side=OrderSide(str(item.get("side", OrderSide.BUY.value)).upper()),
            quantity=float(item.get("quantity", 0.0)),
            order_type=OrderType(str(item.get("order_type", OrderType.MARKET.value)).upper()),
            price=float(item.get("price", 0.0)) or None,
            stop_price=float(item.get("stop_price", 0.0)) or None,
            order_id=client_order_id or broker_order_id or "",
            broker_order_id=broker_order_id,
            state=state,
            filled_quantity=float(item.get("filled_quantity", 0.0)),
            average_fill_price=float(item.get("average_fill_price", 0.0)) or None,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "client_order_id": client_order_id,
                "raw_state": state_text,
                "state_known": state_known,
            },
        )

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _alert_reconcile_required(*, client_id: str, ticker: str, reason: str) -> None:
        logger.error(
            "order_reconcile_required",
            order_id=client_id,
            ticker=ticker,
            reason=reason,
        )
        send_alert(
            "Manual order reconciliation required",
            reason,
            level=AlertLevel.CRITICAL,
            ticker=ticker,
            order_id=client_id,
        )

    def _required_endpoint(self, name: str) -> str:
        value = cast(str | None, getattr(self.endpoints, name))
        if not value:
            raise NotImplementedError(
                f"AlgoLab endpoint '{name}' is not configured. "
                "This feature requires official API endpoint configuration before use."
            )
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
        retry_mode = str(kwargs.pop("retry_mode", "default"))

        last_error: Exception | None = None
        max_attempts = 2 if retry_mode == "place" else max(self.max_retries, 1)
        for attempt in range(max_attempts):
            try:
                headers = (
                    {**base_headers, **self._auth_headers()} if auth_required else base_headers
                )
                self._throttle()
                response = self.session.request(
                    method, url, headers=headers, timeout=timeout, **kwargs
                )

                # Handle stale token: if 401 on first attempt, clear token and retry
                if response.status_code == 401 and auth_required and attempt == 0:
                    with self._auth_lock:
                        self._session_token = None
                        self._session_encrypted = None
                    continue

                if retry_mode == "cancel" and response.status_code == 404:
                    return response

                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if retry_mode == "place":
                    raise
                if attempt == max_attempts - 1:
                    break
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"AlgoLab request failed after {max_attempts} attempts") from last_error

    def _json_request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._request(method, url, **kwargs)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("AlgoLab response payload must be a JSON object")
        return payload
