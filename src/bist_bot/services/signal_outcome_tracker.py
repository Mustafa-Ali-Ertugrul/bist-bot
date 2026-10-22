"""Actionable outcome tracking for AL signals (Z1)."""

from __future__ import annotations

import csv
import json
import threading
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import (
    bist_close_time,
    is_bist_holiday,
    missed_session_days,
    session_eod_datetime,
)
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
        eod_pass: bool = False,
    ) -> list[dict[str, Any]]:
        """Scan positions for exits.

        ``eod_pass=True`` yalnızca ``close_positions_at_eod``'dan gelir: günlük
        barın low/high'ı dünden eski pozisyonlar için geçerlidir; aynı gün
        girişlerde giriş-öncesi low sahte stop üretir, o yüzden o pozisyonlar
        kapanışa göre değerlendirilir.
        """
        if not bool(getattr(self.settings, "OUTCOME_TRACKING_ENABLED", True)):
            return []
        current_time = self._aware_utc(now or datetime.now(UTC))
        market_data = market_data or {}
        with self._lock:
            positions = self._load_json(self.open_path, {})
            if not isinstance(positions, dict):
                positions = {}
            before = json.dumps(positions, sort_keys=True, default=str)
            if eod_pass:
                # EOD guard: aynı seansta açılan pozisyonlar günlük barın
                # low/high'ını görmez (giriş-öncesi fiyatlar sahte STOP_HIT ve
                # MAE üretir — TKFEN 2026-09-23 regresyonu). Dünden eski
                # pozisyonlarda günlük bar tamamen giriş-sonrasıdır.
                market_data = self._eod_filter_market_data(
                    positions, market_data, current_time
                )
            # Update MFE/MAE for open positions from intraday high/low
            self._update_mfe_mae(positions, market_data, current_time)
            prices = self._current_prices(signals, market_data)
            # Son görülen fiyatı sakla: fiyat gelmeyen scan'lerde zaman stopu
            # (MAX_HOLD) bu fiyatla çalışır, pozisyon ölü kalmaz.
            for ticker, pos in positions.items():
                px = prices.get(ticker)
                if px is not None and px > 0:
                    pos["last_price"] = float(px)
                    pos["last_seen_ts"] = current_time.isoformat()
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
                # DB geri yazım — tek oturumda toplu güncelleme (N kapanış = 1 session).
                if self.db is not None:
                    updates: list[tuple[int, str, float, str | None]] = []
                    for row in closed:
                        if row.get("signal_id") is not None:
                            updates.append(
                                (
                                    int(row["signal_id"]),
                                    str(row["outcome"]),
                                    float(row["exit_price"]),
                                    "live_tracker",
                                )
                            )
                    if updates:
                        try:
                            self.db.update_outcomes(updates)
                        except Exception as exc:
                            logger.warning(
                                "outcome_db_batch_update_failed",
                                update_count=len(updates),
                                error=str(exc),
                            )
            logger.info(
                "outcome_scan",
                candidates=len(candidates),
                opened=opened,
                closed=len(closed),
                open_positions=len(positions),
            )
            return closed

    def reconcile_missed_sessions(
        self, fetcher: Any | None = None, *, now: datetime | None = None
    ) -> dict[str, int]:
        """Bilgisayar kapalıyken kaçırılan seansları tarihsel günlük barla kapat.

        Açılışta bir kez çağrılır: EOD'u geçmiş ama hâlâ açık her pozisyon
        için kaçırılan seanslar sırayla replay edilir; barı bulunan ilk seans
        pozisyonu kapatır (STOP_HIT / TARGET_HIT / EOD_CLOSE — çıkış zaman
        damgası o seansın EOD'udur, bugünün değil). Bar bulunamayan günler
        atlanır; hiç bar yoksa pozisyon açık kalır (günün normal akışı kapatır).
        Asla fiyat uydurulmaz.
        """
        current_time = self._aware_utc(now or datetime.now(UTC))
        summary = {"stale": 0, "closed": 0, "skipped_no_bars": 0, "errors": 0}
        if not bool(getattr(self.settings, "MISSED_SESSION_RECONCILE", True)):
            return summary
        if fetcher is None:
            return summary
        max_days = int(getattr(self.settings, "MISSED_SESSION_RECONCILE_MAX_DAYS", 10) or 0)
        with self._lock:
            positions = self._load_json(self.open_path, {})
            if not isinstance(positions, dict) or not positions:
                return summary
            all_closed: list[dict[str, Any]] = []
            for ticker, pos in list(positions.items()):
                try:
                    entry = self._aware_utc(datetime.fromisoformat(pos["entry_ts"]))
                except (KeyError, ValueError, TypeError):
                    summary["errors"] += 1
                    continue
                days = missed_session_days(entry, current_time)
                if max_days > 0:
                    days = days[-max_days:]
                if not days:
                    continue
                summary["stale"] += 1
                try:
                    bars = fetcher.fetch_single(ticker, period="3mo")
                except Exception as exc:
                    logger.warning(
                        "reconcile_fetch_failed", ticker=ticker, error=str(exc)
                    )
                    bars = None
                row = self._replay_position_days(ticker, pos, days, bars)
                if row is None:
                    summary["skipped_no_bars"] += 1
                    continue
                all_closed.append(row)
                del positions[ticker]
                summary["closed"] += 1
                logger.info(
                    "outcome_reconciled_close",
                    ticker=ticker,
                    outcome=row["outcome"],
                    exit_ts=row["exit_ts"],
                )
            if all_closed:
                self._append_closed(all_closed)
                if self.db is not None:
                    updates = [
                        (
                            int(r["signal_id"]),
                            str(r["outcome"]),
                            float(r["exit_price"]),
                            "reconciled_eod",
                        )
                        for r in all_closed
                        if r.get("signal_id") is not None
                    ]
                    if updates:
                        try:
                            self.db.update_outcomes(updates)
                        except Exception as exc:
                            logger.warning(
                                "outcome_db_batch_update_failed",
                                update_count=len(updates),
                                error=str(exc),
                            )
            self._write_json(self.open_path, positions)
        logger.info("outcome_reconcile_completed", **summary)
        return summary

    def _replay_position_days(
        self,
        ticker: str,
        pos: dict[str, Any],
        days: list[date],
        bars: Any | None,
    ) -> dict[str, Any] | None:
        """Kaçırılan seansları sırayla değerlendir; barı bulunan ilk seans kapatır."""
        if bars is None or getattr(bars, "empty", True):
            return None
        try:
            bar_dates = [d.date() for d in bars.index]
        except (AttributeError, TypeError, ValueError):
            return None
        for day in days:
            eod_now = session_eod_datetime(day).astimezone(UTC)
            idx = [i for i, d in enumerate(bar_dates) if d == day]
            if not idx:
                continue
            frame = bars.iloc[[idx[-1]]]
            try:
                close = float(frame["close"].iloc[0])
            except (KeyError, IndexError, TypeError, ValueError):
                try:
                    close = float(frame["Close"].iloc[0])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
            if close <= 0:
                continue
            work = {ticker: pos}
            md = self._eod_filter_market_data(work, {ticker: frame}, eod_now)
            self._update_mfe_mae(work, md, eod_now)
            closed = self._close_due_positions(
                work, {ticker: close}, eod_now, md, None
            )
            if closed:
                return closed[0]
        return None

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

    def _eod_filter_market_data(
        self,
        positions: dict[str, dict[str, Any]],
        market_data: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """EOD pass guard: aynı seansta açılan pozisyonların frame'ini close-only
        yapar. Günlük low giriş-öncesi fiyatları içerir; filtrelenmezse hem
        sahte STOP_HIT hem sahte MAE üretir (TKFEN 2026-09-23 regresyonu).
        Dünden eski pozisyonlarda günlük bar tamamen giriş-sonrasıdır."""
        now_day = now.astimezone(TR).date()
        filtered: dict[str, Any] = {}
        for ticker, payload in market_data.items():
            pos = positions.get(ticker)
            if pos is None:
                filtered[ticker] = payload
                continue
            try:
                entry_day = self._aware_utc(
                    datetime.fromisoformat(pos["entry_ts"])
                ).astimezone(TR).date()
            except (KeyError, ValueError, TypeError):
                filtered[ticker] = payload
                continue
            if entry_day >= now_day:
                filtered[ticker] = self._close_only_frame(payload)
            else:
                filtered[ticker] = payload
        return filtered

    @staticmethod
    def _close_only_frame(payload: Any) -> Any:
        if isinstance(payload, dict):
            return {
                k: SignalOutcomeTracker._close_only_frame(v) for k, v in payload.items()
            }
        if hasattr(payload, "columns"):
            for col in ("close", "Close"):
                if col in payload.columns:
                    try:
                        return payload[[col]]
                    except Exception:
                        return payload
        return payload

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
            entry_time = self._aware_utc(datetime.fromisoformat(pos["entry_ts"]))
            stop = float(pos.get("stop") or 0.0)
            target = float(pos.get("target") or 0.0)
            price = prices.get(ticker)
            if price is None or price <= 0:
                # Fiyat yokken seviye kontrolleri yapılamaz; ama zaman stopu
                # son bilinen fiyatla çalışır. Fiyat da yoksa pozisyonu açık
                # bırakıp bir kez uyar (sessiz ölüm yok).
                max_hold_days = int(getattr(self.settings, "OUTCOME_MAX_HOLD_DAYS", 5) or 0)
                if max_hold_days > 0 and now >= entry_time + timedelta(days=max_hold_days):
                    last = float(pos.get("last_price") or 0.0)
                    if last > 0:
                        logger.warning(
                            "outcome_max_hold_stale_price",
                            ticker=ticker,
                            last_price=last,
                            last_seen_ts=pos.get("last_seen_ts"),
                        )
                        closed.append(
                            self._build_close_row(pos, ticker, last, "MAX_HOLD", now)
                        )
                        del positions[ticker]
                        continue
                    if not pos.get("stuck_warned"):
                        logger.warning(
                            "outcome_unpriced_stuck",
                            ticker=ticker,
                            entry_ts=pos.get("entry_ts"),
                            hint="fiyat hiç gelmedi — pozisyon kapanamıyor",
                        )
                        pos["stuck_warned"] = True
                continue
            # 1 dakikalık bar varsayımı: aynı bar içinde stop ve hedef tetiklenirse stop kazanır
            # Check via current close price (stop/target both crossed -> stop)
            # Also check high/low for intra-bar crossing (if high>=target and low<=stop -> stop wins)
            #
            # Not: EOD pass'te aynı-seans girişler process_scan'da close-only
            # frame'e indirgenir (_eod_filter_market_data); buraya gelen low/high
            # her zaman giriş-sonrasıdır.
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
                max_hold_days = int(getattr(self.settings, "OUTCOME_MAX_HOLD_DAYS", 5) or 0)
                if max_hold_days > 0:
                    if now >= entry_time + timedelta(days=max_hold_days):
                        hit = "MAX_HOLD"
            if hit is None:
                continue
            closed.append(self._build_close_row(pos, ticker, float(price), hit, now))
            del positions[ticker]
            logger.info(
                "outcome_position_closed",
                ticker=ticker,
                outcome=hit,
                exit_price=closed[-1]["exit_price"],
            )
        return closed

    def _build_close_row(
        self,
        pos: dict[str, Any],
        ticker: str,
        price: float,
        hit: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Kapanış satırı üretir (PnL dahil). Fiyat-yokken MAX_HOLD da bu yolu
        kullanır; o durumda ``price`` son bilinen fiyattır."""
        entry_time = self._aware_utc(datetime.fromisoformat(pos["entry_ts"]))
        stop = float(pos.get("stop") or 0.0)
        target = float(pos.get("target") or 0.0)
        entry_price = float(pos["entry_price"])
        quantity = float(pos.get("quantity") or 0.0)
        # Exit price: stop/target fills at/beyond level on gap-through or intra-bar touch.
        if hit == "STOP_HIT" and stop > 0:
            exit_price = min(price, stop)
        elif hit == "TARGET_HIT" and target > 0:
            exit_price = max(price, target)
        else:
            exit_price = price
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
        return row

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
