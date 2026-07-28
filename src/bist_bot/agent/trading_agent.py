import threading
import time
from datetime import UTC
from typing import Any

from bist_bot.agent.audit_log import write_audit
from bist_bot.agent.exit_service import ExitService
from bist_bot.agent.position_manager import PositionManager
from bist_bot.agent.state_machine import AgentOperationalState
from bist_bot.app_logging import get_logger
from bist_bot.risk.costs import TradingCosts
from bist_bot.services.execution_service import ExecutionService

logger = get_logger(__name__, component="trading_agent")


class TradingAgent:
    def __init__(
        self,
        position_manager: PositionManager,
        exit_service: ExitService,
        circuit_breaker: Any,
        db: Any,
        notifier: Any,
        settings: Any,
        data_fetcher: Any = None,
        execution_service: ExecutionService | None = None,
    ) -> None:
        self.position_manager = position_manager
        self.exit_service = exit_service
        self.circuit_breaker = circuit_breaker
        self.db = db
        self.notifier = notifier
        self.settings = settings
        self.data_fetcher = data_fetcher
        self.execution_service = execution_service or ExecutionService(
            db, broker=exit_service.broker, settings=settings
        )
        self._state = AgentOperationalState.IDLE
        self._lock = threading.RLock()
        self._monitor_thread: threading.Thread | None = None
        self._monitor_running = False
        self._resume_generation = 0
        self._resume_timer: threading.Thread | None = None

    @property
    def state(self) -> AgentOperationalState:
        return self._state

    def can_trade(self) -> bool:
        if self._state == AgentOperationalState.HALTED:
            return False
        if self._state == AgentOperationalState.PAUSED:
            return False
        if not self.circuit_breaker.allow_request():
            logger.warning("circuit_breaker_blocks_trading", state=str(self._state))
            return False
        return True

    def on_scan_completed(self, signals: list) -> None:
        if not self.settings.agent.AGENT_ENABLED:
            return
        if self._state == AgentOperationalState.HALTED:
            logger.info("agent_halted_skip")
            return

        with self._lock:
            prev_state = self._state
            self._state = (
                AgentOperationalState.MONITORING
                if self._state != AgentOperationalState.PAUSED
                else AgentOperationalState.PAUSED
            )
            if prev_state != self._state:
                logger.info("agent_state_changed", from_state=prev_state, to_state=self._state)

        self._check_exits()

        if self._state != AgentOperationalState.PAUSED:
            self._check_entries(signals)

        with self._lock:
            if self._state == AgentOperationalState.MONITORING:
                open_count = len(self.position_manager.get_open_positions())
                if open_count == 0:
                    self._state = AgentOperationalState.IDLE
                else:
                    self._state = AgentOperationalState.MONITORING

    def _check_exits(self) -> None:
        try:
            open_positions = self.position_manager.get_open_positions()
            if not open_positions:
                logger.info("agent_no_open_positions_skip_exit")
                return

            tickers = list({str(p["ticker"]) for p in open_positions})
            prices = self._fetch_prices(tickers)

            if not prices:
                logger.warning("agent_no_prices_for_exit_check")
                return

            triggers = self.position_manager.check_exit_conditions(prices)
            for trigger in triggers:
                ticker = trigger["ticker"]
                position_id = trigger["position_id"]
                exit_reason = trigger["exit_reason"]
                current_price = trigger["current_price"]

                logger.info(
                    "exit_triggered",
                    ticker=ticker,
                    exit_reason=exit_reason,
                    current_price=current_price,
                    pnl_pct=trigger.get("pnl_pct", 0),
                )

                success = self.exit_service.exit_position(
                    position_id=position_id,
                    ticker=ticker,
                    quantity=trigger["quantity"],
                    exit_reason=exit_reason,
                    current_price=current_price,
                )

                if success:
                    costs = TradingCosts()
                    fees = costs.sell_cost(current_price * trigger["quantity"])
                    self.position_manager.close_position(
                        position_id=position_id,
                        exit_price=current_price,
                        exit_reason=exit_reason,
                        fees_paid=fees,
                    )

        except Exception:
            logger.exception("exit_check_failed")

    def _entry_signal_types(self) -> set[str]:
        long_only = bool(getattr(self.settings.agent, "AGENT_LONG_ONLY", True))
        if long_only:
            return {"STRONG_BUY"}
        return {"STRONG_BUY", "STRONG_SELL"}

    def _check_entries(self, signals: list) -> None:
        if not self.can_trade():
            return

        agent_settings = self.settings.agent
        daily_trades = self.position_manager.get_daily_trade_count()
        open_positions_count = len(self.position_manager.get_open_positions())

        if daily_trades >= agent_settings.MAX_DAILY_TRADES:
            logger.info(
                "daily_trade_limit_reached",
                count=daily_trades,
                max=agent_settings.MAX_DAILY_TRADES,
            )
            return

        if open_positions_count >= agent_settings.MAX_OPEN_POSITIONS:
            logger.info(
                "max_open_positions_reached",
                count=open_positions_count,
                max=agent_settings.MAX_OPEN_POSITIONS,
            )
            return

        remaining_slots = min(
            agent_settings.MAX_DAILY_TRADES - daily_trades,
            agent_settings.MAX_OPEN_POSITIONS - open_positions_count,
        )

        allowed_types = self._entry_signal_types()
        filtered = [
            s
            for s in signals
            if getattr(s, "signal_type", None) and str(s.signal_type) in allowed_types
        ]

        min_score = agent_settings.MIN_SCORE_THRESHOLD
        filtered = [s for s in filtered if getattr(s, "score", 0) >= min_score]
        filtered = [s for s in filtered if not self.position_manager.get_position(s.ticker)]

        processed = 0
        for signal in filtered:
            if processed >= remaining_slots:
                break

            ticker = signal.ticker
            quantity = signal.position_size if signal.position_size else 0
            if quantity <= 0:
                continue

            require_fill = bool(getattr(agent_settings, "AGENT_REQUIRE_FILL_BEFORE_POSITION", True))
            attempt = self.execution_service.execute_signal(
                signal, force=True, require_fill=require_fill
            )

            if attempt is None or not attempt.accepted:
                write_audit(
                    self.db.manager.engine,
                    event_type="ENTRY_REJECTED",
                    agent_state=self._state.value,
                    ticker=ticker,
                    details={
                        "quantity": quantity,
                        "signal_type": str(signal.signal_type),
                        "score": signal.score,
                        "error": None if attempt is None else attempt.error,
                        "state": None if attempt is None else attempt.state,
                    },
                    trigger_source="SCAN_CYCLE",
                )
                continue

            entry_order_id = attempt.order_db_id if attempt.order_db_id is not None else 0
            entry_price = attempt.fill_price if attempt.fill_price is not None else signal.price

            if signal.stop_loss and signal.target_price:
                self.position_manager.open_position(
                    ticker=ticker,
                    entry_order_id=entry_order_id,
                    entry_price=entry_price,
                    quantity=quantity,
                    stop_loss=signal.stop_loss,
                    target_price=signal.target_price,
                    signal_type=str(signal.signal_type),
                    signal_score=signal.score,
                    position_size_method="kelly" if getattr(signal, "kelly_fraction", 0) else "atr",
                    regime=getattr(signal, "regime", None),
                )

            processed += 1
            write_audit(
                self.db.manager.engine,
                event_type="ENTRY_ORDERED",
                agent_state=self._state.value,
                ticker=ticker,
                details={
                    "quantity": quantity,
                    "signal_type": str(signal.signal_type),
                    "score": signal.score,
                    "order_db_id": entry_order_id,
                    "broker_order_id": attempt.broker_order_id,
                },
                trigger_source="SCAN_CYCLE",
            )

    def _fetch_prices(self, tickers: list[str]) -> dict[str, float]:
        prices: dict[str, float] = {}
        if not self.data_fetcher:
            return prices
        try:
            for ticker in tickers:
                try:
                    df = self.data_fetcher.fetch_single(ticker, period="5d")
                    if df is not None and not df.empty:
                        prices[ticker] = float(df.iloc[-1]["close"])
                except Exception:
                    logger.exception("price_fetch_failed", ticker=ticker)
        except Exception:
            logger.exception("exit_price_fetch_failed")
        return prices

    def emergency_stop(self, reason: str = "manual") -> None:
        with self._lock:
            self._state = AgentOperationalState.HALTED
            self._monitor_running = False
            self._resume_generation += 1
        logger.warning("emergency_stop_triggered", reason=reason)
        write_audit(
            self.db.manager.engine,
            event_type="EMERGENCY_STOP",
            agent_state="HALTED",
            details={"reason": reason},
            trigger_source="MANUAL_COMMAND",
        )

        if self.settings.agent.EMERGENCY_CLOSE_ON_HALT:
            try:
                open_positions = self.position_manager.get_open_positions()
                tickers = [str(p["ticker"]) for p in open_positions]
                prices = self._fetch_prices(tickers)
                for pos in open_positions:
                    ticker = str(pos["ticker"])
                    market_price = prices.get(ticker)
                    if market_price is None:
                        logger.warning(
                            "emergency_exit_no_price",
                            ticker=ticker,
                            position_id=pos.get("id"),
                        )
                        continue
                    success = self.exit_service.exit_position(
                        position_id=pos["id"],
                        ticker=ticker,
                        quantity=pos["quantity"],
                        exit_reason="EMERGENCY",
                        current_price=market_price,
                    )
                    if success:
                        costs = TradingCosts()
                        fees = costs.sell_cost(market_price * float(pos["quantity"]))
                        self.position_manager.close_position(
                            position_id=pos["id"],
                            exit_price=market_price,
                            exit_reason="EMERGENCY",
                            fees_paid=fees,
                        )
            except Exception:
                logger.exception("emergency_close_failed")

    def pause(self, duration_minutes: int = 60) -> str:
        with self._lock:
            self._state = AgentOperationalState.PAUSED
            self._resume_generation += 1
            generation = self._resume_generation
        logger.info("agent_paused", duration_minutes=duration_minutes)
        write_audit(
            self.db.manager.engine,
            event_type="PAUSE_TRADING",
            agent_state="PAUSED",
            details={"duration_minutes": duration_minutes},
            trigger_source="MANUAL_COMMAND",
        )

        if duration_minutes > 0:

            def _auto_resume() -> None:
                time.sleep(duration_minutes * 60)
                with self._lock:
                    if generation != self._resume_generation:
                        return
                    if self._state != AgentOperationalState.PAUSED:
                        return
                self.resume()

            self._resume_timer = threading.Thread(target=_auto_resume, daemon=True)
            self._resume_timer.start()

        return f"Agent paused for {duration_minutes} minutes. Exits still monitored."

    def resume(self) -> str:
        with self._lock:
            self._resume_generation += 1
            self._state = AgentOperationalState.IDLE
        logger.info("agent_resumed")
        write_audit(
            self.db.manager.engine,
            event_type="RESUME_TRADING",
            agent_state="IDLE",
            trigger_source="MANUAL_COMMAND",
        )
        self._ensure_monitor_running()
        return "Agent resumed. Trading enabled."

    def status(self) -> dict[str, Any]:
        open_positions = self.position_manager.get_open_positions()
        daily_trades = self.position_manager.get_daily_trade_count()
        return {
            "agent_state": self._state.value,
            "open_positions": len(open_positions),
            "max_open_positions": self.settings.agent.MAX_OPEN_POSITIONS,
            "daily_trades": daily_trades,
            "max_daily_trades": self.settings.agent.MAX_DAILY_TRADES,
            "positions": [
                {
                    "ticker": p["ticker"],
                    "entry_price": p["entry_price"],
                    "quantity": p["quantity"],
                    "stop_loss": p["stop_loss"],
                    "target_price": p["target_price"],
                    "entry_time": str(p.get("entry_time", "")),
                }
                for p in open_positions
            ],
        }

    def start_monitor(self) -> None:
        self._ensure_monitor_running()

    def stop_monitor(self) -> None:
        self._monitor_running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

    def _ensure_monitor_running(self) -> None:
        if not self.settings.agent.POSITION_MONITOR_ENABLED:
            return
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("position_monitor_started")

    def _monitor_loop(self) -> None:
        interval = self.settings.agent.POSITION_CHECK_INTERVAL_SECONDS
        logger.info("monitor_loop_started", interval_seconds=interval)
        while self._monitor_running:
            try:
                if self._state in {
                    AgentOperationalState.HALTED,
                    AgentOperationalState.MARKET_CLOSED,
                }:
                    time.sleep(interval)
                    continue
                self._check_exits()
                self.exit_service.process_pending_exits()
            except Exception:
                logger.exception("monitor_cycle_failed")
            time.sleep(interval)

    def daily_report(self) -> dict[str, Any]:
        """Günlük portföy raporu oluştur."""
        from datetime import datetime

        open_positions = self.position_manager.get_open_positions()

        today = datetime.now(UTC).date()
        positions_data = []
        total_invested = 0.0

        for pos in open_positions:
            try:
                entry_time_str = pos.get("entry_time")
                if entry_time_str:
                    entry_dt = datetime.fromisoformat(str(entry_time_str).replace("Z", "+00:00"))
                    days_held = (today - entry_dt.date()).days
                else:
                    days_held = 0

                entry_price = float(pos.get("entry_price", 0))
                quantity = float(pos.get("quantity", 0))
                invested = entry_price * quantity
                total_invested += invested

                positions_data.append(
                    {
                        "ticker": pos.get("ticker"),
                        "entry_price": entry_price,
                        "quantity": quantity,
                        "days_held": days_held,
                        "stop_loss": pos.get("stop_loss"),
                        "target_price": pos.get("target_price"),
                    }
                )
            except Exception as e:
                logger.error("report_position_error", ticker=pos.get("ticker"), error=str(e))

        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_positions": len(open_positions),
            "max_positions": self.settings.agent.MAX_OPEN_POSITIONS,
            "total_invested": round(total_invested, 2),
            "positions": positions_data,
            "agent_state": self._state.value,
        }

        logger.info(
            "daily_report_generated",
            total_positions=report["total_positions"],
            total_invested=report["total_invested"],
        )

        return report
