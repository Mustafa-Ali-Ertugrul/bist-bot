"""Research provider interface for future LLM integration (Qwen etc.)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ResearchProvider(ABC):
    """Abstract research layer for signal enrichment and market commentary."""

    @abstractmethod
    def analyze(self, ticker: str, context: dict[str, Any]) -> dict[str, Any]:
        """Return research payload for a given ticker and market context."""
        raise NotImplementedError

    @abstractmethod
    def summarize_signals(self, signals: list[dict[str, Any]]) -> str:
        """Return human-readable summary of actionable signals."""
        raise NotImplementedError


class NullResearchProvider(ResearchProvider):
    """No-op research provider. Safe default until LLM layer is plugged in."""

    def analyze(self, ticker: str, context: dict[str, Any]) -> dict[str, Any]:
        return {"ticker": ticker, "research_available": False, "note": "NullResearchProvider active"}

    def summarize_signals(self, signals: list[dict[str, Any]]) -> str:
        if not signals:
            return "No actionable signals."
        lines = [f"- {s.get('ticker', '?')}: {s.get('signal', 'UNKNOWN')}" for s in signals]
        return "Actionable signals:\n" + "\n".join(lines)
