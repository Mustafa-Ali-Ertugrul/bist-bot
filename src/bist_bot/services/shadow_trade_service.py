"""Persistent observation-only ledger for below-threshold radar signals."""

from __future__ import annotations

import csv
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.config.watchlist import load_watchlist
from bist_bot.strategy.signal_models import Signal

logger = get_logger(__name__, component="shadow_trade")

CSV_FIELDS = (
    "ticker",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "score",
    "agreement_ratio",
    "pnl_pct",
    "pnl_tl",
    "hit",
    "reasons",
)


class ShadowTradeService:
    """Track hypothetical radar positions without any broker dependency."""

    def __init__(
        self,
        settings: Any | None = None,
        results_dir: str | Path = "results",
        robust_tickers: set[str] | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.results_dir = Path(results_dir)
        self.open_path = self.results_dir / "shadow_open.json"
        self.csv_path = self.results_dir / "shadow_pnl.csv"
        self.summary_path = self.results_dir / "shadow_summary_state.json"
        self.robust_tickers = (
            set(load_watchlist("robust")) if robust_tickers is None else set(robust_tickers)
        )
        self._lock = threading.RLock()

    def process_scan(
        self,
        signals: list[Signal],
        market_data: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Close due positions, then record new radar entries."""
        if not bool(getattr(self.settings, "SHADOW_ENABLED", True)):
            return []

        current_time = self._aware_utc(now or datetime.now(UTC))
        with self._lock:
            positions = self._load_json(self.open_path, {})
            if not isinstance(positions, dict):
                positions = {}
            before = json.dumps(positions, sort_keys=True)
            prices = self._current_prices(signals, market_data or {})
            closed = self._close_due_positions(positions, prices, current_time)
            closed_tickers = {row["ticker"] for row in closed}
            candidates = [signal for signal in signals if self._is_shadow_candidate(signal)]
            opened = 0
            for signal in candidates:
                if signal.ticker in positions or signal.ticker in closed_tickers:
                    continue
                positions[signal.ticker] = self._entry_from_signal(signal)
                opened += 1
                logger.info(
                    "shadow_position_opened",
                    ticker=signal.ticker,
                    score=float(signal.score),
                )
            if json.dumps(positions, sort_keys=True) != before or self.open_path.exists():
                self._write_json(self.open_path, positions)
            if closed:
                self._append_closed(closed)
            logger.info(
                "shadow_scan",
                candidates=len(candidates),
                opened=opened,
                closed=len(closed),
                open_positions=len(positions),
            )
            return closed

    def maybe_send_daily_summary(
        self,
        notifier: Any,
        *,
        now: datetime | None = None,
        closed_this_scan: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Send at most one owner summary per Istanbul day, only after a close."""
        if not closed_this_scan or not bool(getattr(self.settings, "SHADOW_ENABLED", True)):
            return False
        current_time = self._aware_utc(now or datetime.now(UTC))
        local_date = current_time.astimezone(ZoneInfo("Europe/Istanbul")).date().isoformat()
        with self._lock:
            state = self._load_json(self.summary_path, {})
            if isinstance(state, dict) and state.get("last_sent_date") == local_date:
                return False
            recent = self._recent_closed(current_time - timedelta(hours=24))
            if not recent:
                return False
            open_count = len(self._load_json(self.open_path, {}))
            avg_pnl = sum(float(row["pnl_pct"]) for row in recent) / len(recent)
            wins = sum(float(row["pnl_pct"]) > 0 for row in recent)
            win_rate = wins / len(recent) * 100.0
            message = (
                "👁️ Gölge PnL (son 24s): "
                f"açık {open_count}, kapanan {len(recent)}, "
                f"ortalama pnl_pct {avg_pnl:.2f}%, win_rate {win_rate:.1f}%"
            )
            if not notifier.send_message(message):
                return False
            self._write_json(self.summary_path, {"last_sent_date": local_date})
            return True

    def _is_shadow_candidate(self, signal: Signal) -> bool:
        if not 0 < float(signal.score) < float(signal.buy_threshold):
            return False
        return not bool(getattr(self.settings, "SHADOW_ONLY_ROBUST", True)) or (
            signal.ticker in self.robust_tickers
        )

    def _entry_from_signal(self, signal: Signal) -> dict[str, Any]:
        entry_time = self._aware_utc(signal.timestamp)
        entry_price = float(signal.price)
        stop = float(signal.stop_loss or 0.0)
        risk_budget = float(getattr(self.settings, "INITIAL_CAPITAL", 0.0)) * (
            float(getattr(self.settings, "MAX_TOTAL_RISK_PCT", 0.0)) / 100.0
        )
        if signal.position_size is not None and signal.position_size > 0:
            quantity = float(signal.position_size)
        elif 0 < stop < entry_price:
            quantity = risk_budget / (entry_price - stop)
        else:
            quantity = risk_budget / entry_price if entry_price > 0 else 0.0
        return {
            "ticker": signal.ticker,
            "entry_price": entry_price,
            "entry_time": entry_time.isoformat(),
            "stop": stop,
            "target": float(signal.target_price or 0.0),
            "score": float(signal.score),
            "agreement_ratio": signal.agreement_ratio,
            "reasons": " | ".join(signal.reasons),
            "holding_days": max(int(getattr(self.settings, "SHADOW_HOLDING_DAYS", 5)), 1),
            "quantity": quantity,
        }

    def _close_due_positions(
        self,
        positions: dict[str, dict[str, Any]],
        prices: dict[str, float],
        now: datetime,
    ) -> list[dict[str, Any]]:
        closed: list[dict[str, Any]] = []
        for ticker, position in list(positions.items()):
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue
            entry_time = self._aware_utc(datetime.fromisoformat(position["entry_time"]))
            stop = float(position.get("stop") or 0.0)
            target = float(position.get("target") or 0.0)
            if stop > 0 and price <= stop:
                hit = "stop"
            elif target > 0 and price >= target:
                hit = "target"
            elif now >= entry_time + timedelta(days=int(position["holding_days"])):
                hit = "timeout"
            else:
                continue
            entry_price = float(position["entry_price"])
            pnl_pct = (price / entry_price - 1.0) * 100.0
            pnl_tl = (price - entry_price) * float(position.get("quantity") or 0.0)
            row = {
                "ticker": ticker,
                "entry_time": entry_time.isoformat(),
                "entry_price": entry_price,
                "exit_time": now.isoformat(),
                "exit_price": price,
                "score": float(position["score"]),
                "agreement_ratio": position.get("agreement_ratio"),
                "pnl_pct": round(pnl_pct, 6),
                "pnl_tl": round(pnl_tl, 2),
                "hit": hit,
                "reasons": position.get("reasons", ""),
            }
            closed.append(row)
            del positions[ticker]
            logger.info("shadow_position_closed", ticker=ticker, hit=hit, pnl_pct=pnl_pct)
        return closed

    def _current_prices(
        self, signals: list[Signal], market_data: dict[str, Any]
    ) -> dict[str, float]:
        prices = {signal.ticker: float(signal.price) for signal in signals if signal.price > 0}
        for ticker, payload in market_data.items():
            close = self._latest_close(payload)
            if close is not None and close > 0:
                prices[ticker] = close
        return prices

    @staticmethod
    def _latest_close(payload: Any) -> float | None:
        candidates = []
        if isinstance(payload, dict):
            candidates.extend([payload.get("trigger"), payload.get("trend")])
        candidates.append(payload)
        for frame in candidates:
            if frame is None or not hasattr(frame, "iloc"):
                continue
            for column in ("Close", "close"):
                try:
                    value = float(frame[column].iloc[-1])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                return value
        return None

    def _append_closed(self, rows: list[dict[str, Any]]) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        write_header = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerows(rows)

    def _recent_closed(self, cutoff: datetime) -> list[dict[str, str]]:
        if not self.csv_path.exists():
            return []
        with self.csv_path.open(encoding="utf-8", newline="") as handle:
            return [
                row
                for row in csv.DictReader(handle)
                if self._aware_utc(datetime.fromisoformat(row["exit_time"])) >= cutoff
            ]

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
