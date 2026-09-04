from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from bist_bot.agent.audit_log import write_audit
from bist_bot.agent.settlement import calculate_settlement
from bist_bot.agent.state_machine import ExitReason, PositionState
from bist_bot.app_logging import get_logger
from bist_bot.db.database import LivePositionRecord

logger = get_logger(__name__, component="position_manager")


class PositionManager:
    def __init__(self, db: Any, settings: Any) -> None:
        self.db = db
        self.settings = settings

    def open_position(
        self,
        ticker: str,
        entry_order_id: int,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        target_price: float,
        signal_type: str,
        signal_score: float,
        risk_reward_ratio: float | None = None,
        position_size_method: str | None = None,
        regime: str | None = None,
    ) -> LivePositionRecord | None:
        entry_time = datetime.now(UTC)
        agent_settings = self.settings.agent
        settlement_days = int(getattr(agent_settings, "SETTLEMENT_DAYS", 2))
        settlement_dt = calculate_settlement(entry_time, settlement_days)

        position = LivePositionRecord(
            ticker=ticker,
            side="LONG",
            entry_order_id=entry_order_id,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=entry_time,
            stop_loss=stop_loss,
            target_price=target_price,
            risk_reward_ratio=risk_reward_ratio,
            position_size_method=position_size_method,
            settlement_date=settlement_dt,
            state=PositionState.POSITION_OPEN.value,
            signal_type=signal_type,
            signal_score=signal_score,
            regime=regime,
        )
        try:
            with self.db.manager.engine.begin() as conn:
                conn.execute(
                    text(
                        """INSERT INTO live_positions
                        (ticker, side, entry_order_id, entry_price, quantity, entry_time,
                         stop_loss, target_price, risk_reward_ratio, position_size_method,
                         settlement_date, state, signal_type, signal_score, regime, fees_paid,
                         created_at, updated_at)
                        VALUES (:ticker, :side, :entry_order_id, :entry_price, :quantity, :entry_time,
                                :stop_loss, :target_price, :risk_reward_ratio, :position_size_method,
                                :settlement_date, :state, :signal_type, :signal_score, :regime, :fees_paid,
                                :created_at, :updated_at)"""
                    ),
                    {
                        "ticker": ticker,
                        "side": "LONG",
                        "entry_order_id": entry_order_id,
                        "entry_price": entry_price,
                        "quantity": quantity,
                        "entry_time": entry_time,
                        "stop_loss": stop_loss,
                        "target_price": target_price,
                        "risk_reward_ratio": risk_reward_ratio,
                        "position_size_method": position_size_method,
                        "settlement_date": settlement_dt,
                        "state": PositionState.POSITION_OPEN.value,
                        "signal_type": signal_type,
                        "signal_score": signal_score,
                        "regime": regime,
                        "fees_paid": 0.0,
                        "created_at": entry_time,
                        "updated_at": entry_time,
                    },
                )
            logger.info(
                "position_opened", ticker=ticker, quantity=quantity, entry_price=entry_price
            )
            write_audit(
                self.db.manager.engine,
                event_type="POSITION_OPENED",
                agent_state="MONITORING",
                ticker=ticker,
                position_id=None,
                details={
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "stop_loss": stop_loss,
                    "target_price": target_price,
                    "signal_type": signal_type,
                },
                trigger_source="SCAN_CYCLE",
            )
            return position
        except Exception:
            logger.exception("position_open_failed", ticker=ticker)
            return None

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str,
        exit_order_id: int | None = None,
        fees_paid: float = 0.0,
    ) -> None:
        exit_time = datetime.now(UTC)
        try:
            with self.db.manager.engine.begin() as conn:
                row = (
                    conn.execute(
                        text("SELECT entry_price, quantity FROM live_positions WHERE id = :id"),
                        {"id": position_id},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    logger.warning("position_close_not_found", position_id=position_id)
                    return
                entry_price = float(row["entry_price"])
                quantity = float(row["quantity"])
                realized_pnl = (exit_price - entry_price) * quantity - fees_paid
                realized_pnl_pct = (
                    ((exit_price - entry_price) / entry_price * 100) if entry_price else 0.0
                )

                conn.execute(
                    text(
                        """UPDATE live_positions SET state=:state, exit_price=:exit_price,
                        exit_time=:exit_time, exit_reason=:exit_reason, exit_order_id=:exit_order_id,
                        realized_pnl=:realized_pnl, realized_pnl_pct=:realized_pnl_pct,
                        fees_paid=:fees_paid, updated_at=:updated_at WHERE id=:id"""
                    ),
                    {
                        "state": PositionState.CLOSED.value,
                        "exit_price": exit_price,
                        "exit_time": exit_time,
                        "exit_reason": exit_reason,
                        "exit_order_id": exit_order_id,
                        "realized_pnl": round(realized_pnl, 2),
                        "realized_pnl_pct": round(realized_pnl_pct, 2),
                        "fees_paid": fees_paid,
                        "updated_at": exit_time,
                        "id": position_id,
                    },
                )
            logger.info(
                "position_closed",
                position_id=position_id,
                exit_price=exit_price,
                exit_reason=exit_reason,
                pnl=round(realized_pnl, 2),
            )
            write_audit(
                self.db.manager.engine,
                event_type="POSITION_CLOSED",
                agent_state="MONITORING",
                position_id=position_id,
                details={
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "realized_pnl": round(realized_pnl, 2),
                    "realized_pnl_pct": round(realized_pnl_pct, 2),
                },
                trigger_source="POSITION_MONITOR",
            )
        except Exception:
            logger.exception("position_close_failed", position_id=position_id)

    def get_open_positions(self) -> list[dict[str, Any]]:
        try:
            with self.db.manager.engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT * FROM live_positions WHERE state = :state ORDER BY entry_time DESC"
                        ),
                        {"state": PositionState.POSITION_OPEN.value},
                    )
                    .mappings()
                    .all()
                )
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("get_open_positions_failed")
            return []

    def get_position(self, ticker: str) -> dict[str, Any] | None:
        try:
            with self.db.manager.engine.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            "SELECT * FROM live_positions WHERE ticker=:ticker AND state=:state LIMIT 1"
                        ),
                        {"ticker": ticker, "state": PositionState.POSITION_OPEN.value},
                    )
                    .mappings()
                    .first()
                )
            return dict(row) if row else None
        except Exception:
            logger.exception("get_position_failed", ticker=ticker)
            return None

    def _update_stop_loss(self, position_id: int, new_stop: float) -> None:
        """Ratchet a position's stop loss upward (trailing stop persistence).

        Best-effort: on failure the exit check continues with the in-memory
        stop for this cycle; the next cycle recomputes the trail from bars, so
        a restart only loses the persisted ratchet, never the protection.
        """
        try:
            with self.db.manager.engine.begin() as conn:
                conn.execute(
                    text(
                        """UPDATE live_positions SET stop_loss=:stop, updated_at=:ts
                        WHERE id=:id AND state=:state"""
                    ),
                    {
                        "stop": round(new_stop, 4),
                        "ts": datetime.now(UTC),
                        "id": position_id,
                        "state": PositionState.POSITION_OPEN.value,
                    },
                )
            logger.info(
                "trailing_stop_updated", position_id=position_id, new_stop=round(new_stop, 4)
            )
        except Exception:
            logger.exception("trailing_stop_update_failed", position_id=position_id)

    def check_exit_conditions(
        self,
        prices: dict[str, float],
        atr_map: dict[str, float] | None = None,
        closes_map: dict[str, list[tuple[str, float]]] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate exit triggers for open positions.

        prices: ticker -> latest price (required).
        atr_map: ticker -> ATR14 (Deney M ATR trailing stop; optional).
        closes_map: ticker -> [(iso_date, close), ...] daily closes since
            roughly entry (peak-close tracking; optional).

        ATR trailing (Deney M, docs/retail_abone_ekonomisi.md §17): trail =
        peak_close - TRAILING_ATR_MULT * ATR14, only ever tightening the
        original stop. When the trail rises above the stored stop it is
        persisted via _update_stop_loss so restarts keep the ratchet. A hit on
        a ratcheted stop exits with TRAILING_STOP (vs STOP_HIT on the original).
        """
        open_positions = self.get_open_positions()
        triggers: list[dict[str, Any]] = []
        atr_mult = float(getattr(self.settings.agent, "TRAILING_ATR_MULT", 0.0) or 0.0)
        trail_enabled = bool(getattr(self.settings.agent, "TRAILING_STOP_ENABLED", False))

        for pos in open_positions:
            ticker = str(pos["ticker"])
            current_price = prices.get(ticker)
            if current_price is None:
                continue

            original_stop = float(pos["stop_loss"])
            stop_loss = original_stop
            target_price = float(pos["target_price"])
            entry_price = float(pos["entry_price"])
            reason = None

            if trail_enabled and atr_mult > 0 and atr_map and ticker in atr_map and closes_map:
                atr = float(atr_map[ticker])
                if atr > 0:
                    entry_date = str(pos.get("entry_time") or "")[:10]
                    peak = current_price
                    for bar_date, close in closes_map.get(ticker, []):
                        if bar_date >= entry_date and close > peak:
                            peak = close
                    trail = peak - atr_mult * atr
                    if trail > stop_loss:
                        self._update_stop_loss(int(pos["id"]), trail)
                        stop_loss = trail

            if current_price <= stop_loss:
                reason = (
                    ExitReason.TRAILING_STOP if stop_loss > original_stop else ExitReason.STOP_HIT
                )
            elif current_price >= target_price:
                reason = ExitReason.TARGET_HIT

            # Takvim-gunu kurali: MAX_HOLDING_DAYS takvim gunu sonra otomatik kapat
            # (28 takvim gunu ~= 20 is gunu; bkz. Deney H, docs/retail_abone_ekonomisi.md)
            if reason is None and pos.get("entry_time"):
                try:
                    entry_dt = datetime.fromisoformat(str(pos["entry_time"]).replace("Z", "+00:00"))
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=UTC)
                    now = datetime.now(UTC)
                    days_held = (now - entry_dt).days
                    max_days = self.settings.agent.MAX_HOLDING_DAYS
                    if days_held >= max_days:
                        reason = ExitReason.MAX_HOLDING_DAYS
                        logger.info(
                            "holding_days_limit",
                            ticker=ticker,
                            days_held=days_held,
                            max_days=max_days,
                        )
                except (ValueError, TypeError):
                    pass

            if reason:
                triggers.append(
                    {
                        "position_id": pos["id"],
                        "ticker": ticker,
                        "exit_reason": reason.value,
                        "current_price": current_price,
                        "entry_price": entry_price,
                        "quantity": pos["quantity"],
                        "pnl_pct": round((current_price - entry_price) / entry_price * 100, 2)
                        if entry_price
                        else 0,
                    }
                )

        return triggers

    def recover_from_restart(self, broker_positions: list[dict[str, Any]]) -> None:
        if not self.settings.agent.RESTART_RECOVERY_ENABLED:
            return
        try:
            db_positions = self.get_open_positions()
            broker_tickers = {str(p.get("ticker", "")) for p in broker_positions if p.get("ticker")}

            for pos in db_positions:
                ticker = str(pos["ticker"])
                if ticker not in broker_tickers:
                    logger.warning("position_orphaned_in_db", ticker=ticker, position_id=pos["id"])
                    write_audit(
                        self.db.manager.engine,
                        event_type="RESTART_RECOVERY",
                        agent_state="IDLE",
                        ticker=ticker,
                        position_id=pos["id"],
                        details={"action": "orphaned_db_position_found"},
                        trigger_source="SYSTEM_RECOVERY",
                    )

            logger.info(
                "recovery_complete",
                db_positions=len(db_positions),
                broker_positions=len(broker_positions),
            )
        except Exception:
            logger.exception("recovery_failed")

    def get_daily_trade_count(self) -> int:
        today = datetime.now(UTC).date()
        try:
            with self.db.manager.engine.connect() as conn:
                count = conn.execute(
                    text("SELECT COUNT(*) FROM live_positions WHERE date(entry_time) = :today"),
                    {"today": today.isoformat()},
                ).scalar_one()
            return int(count)
        except Exception:
            return 0
