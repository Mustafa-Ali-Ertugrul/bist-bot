"""Custom exception classes for BIST-Bot error handling."""

from __future__ import annotations


class DataFetchError(Exception):
    """Raised when data fetching from exchanges or APIs fails."""

    def __init__(
        self,
        message: str = "Failed to fetch data",
        ticker: str | None = None,
        details: str | None = None,
    ) -> None:
        self.ticker = ticker
        self.details = details
        super().__init__(f"{message} (ticker={ticker}, details={details})")


class SignalProcessingError(Exception):
    """Raised when signal processing or analysis fails."""

    def __init__(
        self,
        message: str = "Signal processing failed",
        signal_data: dict | None = None,
        details: str | None = None,
    ) -> None:
        self.signal_data = signal_data
        self.details = details
        super().__init__(f"{message} (details={details})")


class OrderExecutionError(Exception):
    """Raised when order execution fails."""

    def __init__(
        self,
        message: str = "Order execution failed",
        order_data: dict | None = None,
        broker_code: str | None = None,
        details: str | None = None,
    ) -> None:
        self.order_data = order_data
        self.broker_code = broker_code
        self.details = details
        super().__init__(f"{message} (broker={broker_code}, details={details})")
