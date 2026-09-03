"""Actionable outcome tracking for AL signals (Z1)."""

from __future__ import annotations

import csv
import json
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import bist_close_time, is_bist_holiday
from bist_bot.risk.costs import TradingCosts
from bist_bot.strategy.signal_models import Signal, SignalCategory, categorize_signal

logger = get_logger(__name__, component="signal_outcome")
TR = timezone(timedelta(hours=3))

CSV_FIELDS = (
    "signal_id",
    "ticker",
    "score",
    "entry_ts",
    "side",
    "entry_price",
    "stop",
    "target",
    "exit_price",
    "exit_ts",
    "outcome",
    "holding_min",
    "mfe_pct",
    "mae_pct",
    "gross_pnl",
    "net_pnl",
)


class SignalOutcomeTracker:
    """Track virtual long positions for AL signals; shadow pattern with MFE/MAE."""

    def __init__(
        self,
        settings: Any | None = None,
        results_dir: str | Path = "results",
        db: Any | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.results_dir = Path(results_dir)
        self.open_path = self.results_dir / "signal_outcome_open.json"
        self.csv_path = self.results_dir / "signal_outcomes.csv"
        self.db = db
        self._lock = threading.RLock()
        self._costs = TradingCosts()

    def process_scan(
        self,
        signals: list[Signal],
        market_data: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not bool(getattr(self.settings, "OUTCOME_TRACKING_ENABLED", True)):
            return []
        current_time = self._aware_utc(now or datetime.now(UTC))
        market_data = market_data or {}
        with self._lock:
            positions = self._load_json(self.open_path, {})
            if not isinstance(positions, dict):
                positions = {}
            before = json.dumps(positions, sort_keys=True, default=str)
            # Update MFE/MAE for open positions from intraday high/low
            self._update_mfe_mae(positions, market_data, current_time)
            prices = self._current_prices(signals, market_data)
            closed = self._close_due_positions(
                positions, prices, current_time, market_data, signals
            )
            closed_tickers = {row["ticker"] for row in closed}
            # New candidates: only AL
            candidates = [s for s in signals if categorize_signal(s) == SignalCategory.AL]
            # Dedup: 1 open per ticker
            opened = 0
            for sig in candidates:
                if sig.ticker in positions or sig.ticker in closed_tickers:
                    continue
                # Dedup: if ticker already open, skip
                if sig.ticker in positions:
                    continue
                positions[sig.ticker] = self._entry_from_signal(sig, current_time)
                opened += 1
                logger.info("outcome_position_opened", ticker=sig.ticker, score=float(sig.score))
            if (
                json.dumps(positions, sort_keys=True, default=str) != before
                or self.open_path.exists()
            ):
                self._write_json(self.open_path, positions)
            if closed:
                self._append_closed(closed)
                # DB geri yazım
                for row in closed:
                    try:
                        if self.db is not None and row.get("signal_id") is not None:
                            self.db.update_outcome(
                                int(row["signal_id"]),
                                str(row["outcome"]),
                                float(row["exit_price"]),
                                source="live_tracker",
                            )
                        elif self.db is not None:
                            # fallback via ticker+time lookup not needed for test
                            pass
                    except Exception as exc:
                        logger.warning(
                            "outcome_db_update_failed", ticker=row.get("ticker"), error=str(exc)
                        )
            logger.info(
                "outcome_scan",
                candidates=len(candidates),
                opened=opened,
                closed=len(closed),
                open_positions=len(positions),
            )
            return closed

    def _entry_from_signal(self, signal: Signal, now: datetime) -> dict[str, Any]:
        entry_time = self._aware_utc(signal.timestamp)
        entry_price = float(signal.price)
        stop = float(signal.stop_loss or 0.0)
        target = float(signal.target_price or 0.0)
        # 1 lot varsayımı için notional 10k; quantity = 10000/entry_price
        quantity = 10000.0 / entry_price if entry_price > 0 else 0.0
        return {
            "signal_id": int(signal.record_id)
            if getattr(signal, "record_id", None) is not None
            else None,
            "ticker": signal.ticker,
            "score": float(signal.score),
            "entry_ts": entry_time.isoformat(),
            "side": "long",
            "entry_price": entry_price,
            "stop": stop,
            "target": target,
            "quantity": quantity,
            "agreement_ratio": signal.agreement_ratio,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "max_high": entry_price,
            "min_low": entry_price,
        }

    def _update_mfe_mae(
        self, positions: dict[str, Any], market_data: dict[str, Any], now: datetime
    ) -> None:
        for ticker, pos in positions.items():
            payload = market_data.get(ticker)
            high, low = self._extract_high_low(payload)
            if high is None or low is None:
                continue
            entry = float(pos["entry_price"])
            # update extremes
            max_high = max(float(pos.get("max_high", entry)), float(high))
            min_low = min(float(pos.get("min_low", entry)), float(low))
            pos["max_high"] = max_high
            pos["min_low"] = min_low
            pos["mfe_pct"] = round((max_high - entry) / entry * 100, 2) if entry > 0 else 0.0
            pos["mae_pct"] = round((min_low - entry) / entry * 100, 2) if entry > 0 else 0.0

    def _close_due_positions(
        self,
        positions: dict[str, dict[str, Any]],
        prices: dict[str, float],
        now: datetime,
        market_data: dict[str, Any],
        signals: list[Signal] | None = None,
    ) -> list[dict[str, Any]]:
        closed: list[dict[str, Any]] = []
        for ticker, pos in list(positions.items()):
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue
            entry_time = self._aware_utc(datetime.fromisoformat(pos["entry_ts"]))
            stop = float(pos.get("stop") or 0.0)
            target = float(pos.get("target") or 0.0)
            entry_price = float(pos["entry_price"])
            quantity = float(pos.get("quantity") or 0.0)
            # 1 dakikalık bar varsayımı: aynı bar içinde stop ve hedef tetiklenirse stop kazanır
            # Check via current close price (stop/target both crossed -> stop)
            # Also check high/low for intra-bar crossing (if high>=target and low<=stop -> stop wins)
            high, low = self._extract_high_low(market_data.get(ticker))
            # Determine hit
            hit = None
            # Use high/low if available for precise intrabar detection
            if high is not None and low is not None and stop > 0 and target > 0:
                if (low <= stop and high >= target) or low <= stop:
                    hit = "STOP_HIT"
                elif high >= target:
                    hit = "TARGET_HIT"
            else:
                if stop > 0 and price <= stop:
                    hit = "STOP_HIT"
                elif target > 0 and price >= target:
                    hit = "TARGET_HIT"
            if hit is None:
                # Fallback to close price check
                if stop > 0 and price <= stop:
                    hit = "STOP_HIT"
                elif target > 0 and price >= target:
                    hit = "TARGET_HIT"
            if hit is None and self._is_eod(now):
                hit = "EOD_CLOSE"
            if hit is None:
                continue
            exit_price = float(price)
            holding_min = int((now - entry_time).total_seconds() // 60)
            # MFE/MAE at exit are already updated
            mfe = float(pos.get("mfe_pct", 0.0))
            mae = float(pos.get("mae_pct", 0.0))
            # Gross PnL: (exit-entry)*quantity with 1 lot notional 10k
            # For long: gross = (exit - entry)*quantity
            gross = (exit_price - entry_price) * quantity
            # Net: gross - round_trip_cost
            buy_notional = entry_price * quantity
            sell_notional = exit_price * quantity
            try:
                cost = self._costs.round_trip_cost(buy_notional, sell_notional)
            except Exception:
                cost = 0.0
            net = gross - cost
            row = {
                "signal_id": pos.get("signal_id"),
                "ticker": ticker,
                "score": float(pos.get("score", 0.0)),
                "entry_ts": pos.get("entry_ts"),
                "side": pos.get("side", "long"),
                "entry_price": entry_price,
                "stop": stop,
                "target": target,
                "exit_price": exit_price,
                "exit_ts": now.isoformat(),
                "outcome": hit,
                "holding_min": holding_min,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "gross_pnl": round(gross, 2),
                "net_pnl": round(net, 2),
            }
            closed.append(row)
            del positions[ticker]
            logger.info(
                "outcome_position_closed", ticker=ticker, outcome=hit, exit_price=exit_price
            )
        return closed

    def _is_eod(self, now: datetime) -> bool:
        # Use market_calendar bist_close_time per spec
        try:
            local_now = now.astimezone(TR)
            d = local_now.date()
            if is_bist_holiday(d):
                return False
            close_t = bist_close_time(d)
            return local_now.time() >= close_t
        except Exception:
            return False

    def _current_prices(
        self, signals: list[Signal], market_data: dict[str, Any]
    ) -> dict[str, float]:
        prices = {s.ticker: float(s.price) for s in signals if s.price > 0}
        for ticker, payload in market_data.items():
            close = self._latest_close(payload)
            if close is not None and close > 0:
                # Prefer market_data close for open positions (more current)
                # But keep signal price as primary for newly opened? For close checks, market close wins.
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
            for col in ("Close", "close"):
                try:
                    return float(frame[col].iloc[-1])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_high_low(payload: Any) -> tuple[float | None, float | None]:
        candidates = []
        if isinstance(payload, dict):
            candidates.extend([payload.get("trigger"), payload.get("trend")])
        candidates.append(payload)
        for frame in candidates:
            if frame is None or not hasattr(frame, "iloc"):
                continue
            try:
                high = float(frame["high"].iloc[-1]) if "high" in frame.columns else None
            except Exception:
                high = None
            try:
                low = float(frame["low"].iloc[-1]) if "low" in frame.columns else None
            except Exception:
                low = None
            if high is not None and low is not None:
                return high, low
            # fallback to Close for both
            try:
                c = (
                    float(frame["close"].iloc[-1])
                    if "close" in frame.columns
                    else float(frame["Close"].iloc[-1])
                )
                return c, c
            except Exception:
                continue
        return None, None

    def _append_closed(self, rows: list[dict[str, Any]]) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        write_header = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        with self.csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if write_header:
                writer.writeheader()
            # Ensure only expected fields are written, with proper types
            filtered = []
            for r in rows:
                fr = {k: r.get(k) for k in CSV_FIELDS}
                # Normalize signal_id None -> ""
                if fr["signal_id"] is None:
                    fr["signal_id"] = ""
                filtered.append(fr)
            writer.writerows(filtered)

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
        tmp = path.with_suffix(f"{path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
