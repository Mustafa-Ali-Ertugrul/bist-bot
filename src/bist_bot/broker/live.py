"""Live broker that delegates to a real venue adapter (AlgoLab).

``BROKER_PROVIDER`` determines the underlying adapter:

- ``algolab`` → ``AlgoLabBroker``

Alpaca support has been removed (US-market venue no longer integrated).
All other providers raise ``ValueError`` at construction time so that
misconfigurations fail early rather than at order-submission time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bist_bot.app_logging import get_logger
from bist_bot.execution.base import (
    AccountInfo,
    BaseExecutionProvider,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

if TYPE_CHECKING:
    from bist_bot.config.settings import Settings

logger = get_logger(__name__, component="broker")

_UNSUPPORTED_MSG = "BROKER_PROVIDER={provider!r} is not supported by LiveBroker. Use 'algolab'."


def _resolve_venue(provider: str, settings: Settings) -> BaseExecutionProvider:
    """Instantiate the underlying execution provider for *provider*."""
    provider = provider.lower().strip()

    if provider == "algolab":
        from bist_bot.execution.algolab_broker import AlgoLabBroker, AlgoLabCredentials

        return AlgoLabBroker(
            AlgoLabCredentials(
                api_key=settings.ALGOLAB_API_KEY,
                username=settings.ALGOLAB_USERNAME,
                password=settings.ALGOLAB_PASSWORD,
                otp_code=settings.ALGOLAB_OTP_CODE or None,
            ),
            dry_run=settings.ALGOLAB_DRY_RUN,
        )

    raise ValueError(_UNSUPPORTED_MSG.format(provider=provider))


class LiveBroker(BaseExecutionProvider):
    """Thin delegation layer over a real venue adapter.

    Resolves ``BROKER_PROVIDER`` → concrete ``BaseExecutionProvider`` and
    forwards every call.  This keeps ``Broker`` / ``OrderExecutor`` code
    provider-agnostic while ensuring live mode actually works.
    """

    def __init__(self, provider: str, settings: Settings) -> None:
        self._provider_name = provider.lower().strip()
        self._venue = _resolve_venue(self._provider_name, settings)
        logger.info(
            "live_broker_init",
            provider=self._provider_name,
            venue_type=type(self._venue).__name__,
        )

    # --- BaseExecutionProvider interface ---

    def authenticate(self) -> bool:
        ok = self._venue.authenticate()
        logger.info(
            "live_broker_auth",
            provider=self._provider_name,
            success=ok,
        )
        return ok

    def get_positions(self) -> list[Position]:
        return self._venue.get_positions()

    def get_account_info(self) -> AccountInfo:
        return self._venue.get_account_info()

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        result = self._venue.place_order(
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
        )
        logger.info(
            "live_broker_order",
            provider=self._provider_name,
            ticker=ticker,
            side=side.value,
            quantity=quantity,
            accepted=result.accepted,
            state=result.state.value,
            order_id=result.order_id,
        )
        return result

    def submit_order(
        self,
        ticker: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> OrderResult:
        """Product API alias used by ``OrderExecutor``."""
        from bist_bot.broker.base import coerce_order_type, coerce_side

        return self.place_order(
            ticker=ticker,
            side=coerce_side(side),
            quantity=float(quantity),
            order_type=coerce_order_type(order_type),
            price=price,
            stop_price=stop_price,
        )

    def cancel_order(self, order_id: str) -> bool:
        ok = self._venue.cancel_order(order_id)
        logger.info(
            "live_broker_cancel",
            provider=self._provider_name,
            order_id=order_id,
            cancelled=ok,
        )
        return ok

    def get_order_status(self, order_id: str) -> OrderStatus:
        return self._venue.get_order_status(order_id)

    def get_open_orders(self) -> list[Order]:
        return self._venue.get_open_orders()

    # --- Convenience: expose venue-level helpers ---

    @property
    def venue(self) -> BaseExecutionProvider:
        """Direct access to the underlying venue adapter (for advanced use)."""
        return self._venue

    @property
    def provider_name(self) -> str:
        return self._provider_name


__all__ = ["LiveBroker"]
