import json
from typing import Any

from sqlalchemy import text

from bist_bot.agent.audit_log import write_audit
from bist_bot.app_logging import get_logger
from bist_bot.execution.base import OrderSide, OrderType
from bist_bot.risk.costs import TradingCosts

logger = get_logger(__name__, component="exit_service")


def _parse_exit_reason(metadata_json: Any) -> str:
    """metadata_json'dan gercek exit_reason'u cikar.

    Ham JSON blob'unu (vaka #2) exit_reason kolonuna yazmak rapor ve
    score-correlation win/loss siniflandirmasini bozar.
    """
    if not metadata_json:
        return "UNKNOWN"
    try:
        parsed = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
        if isinstance(parsed, dict):
            return str(parsed.get("exit_reason") or "UNKNOWN")
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return "UNKNOWN"


class ExitService:
    def __init__(self, broker: Any, db: Any, settings: Any) -> None:
        self.broker = broker
        self.db = db
        self.settings = settings
        self.costs = TradingCosts()

    def exit_position(
        self,
        position_id: int,
        ticker: str,
        quantity: float,
        exit_reason: str,
        current_price: float,
    ) -> bool:
        order_type_str = self.settings.agent.EXIT_ORDER_TYPE
        try:
            order_type = OrderType[order_type_str]
        except KeyError:
            order_type = OrderType.MARKET

        if not getattr(self.broker, "authenticate", lambda: False)():
            logger.error("exit_broker_auth_failed", ticker=ticker)
            return False

        try:
            order = self.db.create_order(
                ticker=ticker,
                side=OrderSide.SELL.value,
                quantity=quantity,
                order_type=order_type.value,
                price=current_price,
                state="CREATED",
                position_id=position_id,
                purpose="EXIT",
                metadata_json={"exit_reason": exit_reason},
            )
        except Exception:
            logger.exception("exit_order_db_failed", ticker=ticker)
            order = None

        result = self.broker.place_order(
            ticker=ticker,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=order_type,
            price=current_price,
        )

        if result.accepted:
            # Emri DB'ye isle: broker_order_id + SENT, yoksa pending-exit
            # takibi bu emri asla goremez.
            if order is not None and result.broker_order_id:
                try:
                    self.db.update_order(
                        order["id"],
                        state="SENT",
                        broker_order_id=result.broker_order_id,
                    )
                except Exception:
                    logger.exception(
                        "exit_order_tracking_update_failed", broker_order_id=result.broker_order_id
                    )
            logger.info(
                "exit_order_placed",
                ticker=ticker,
                position_id=position_id,
                reason=exit_reason,
                broker_order_id=result.broker_order_id,
            )
            write_audit(
                self.db.manager.engine,
                event_type="EXIT_ORDERED",
                agent_state="MONITORING",
                ticker=ticker,
                position_id=position_id,
                details={
                    "exit_reason": exit_reason,
                    "current_price": current_price,
                    "quantity": quantity,
                    "broker_order_id": result.broker_order_id,
                },
                trigger_source="POSITION_MONITOR",
            )
            return True
        else:
            logger.warning(
                "exit_order_rejected",
                ticker=ticker,
                reason=exit_reason,
                message=result.message,
            )
            return False

    def process_pending_exits(self) -> None:
        try:
            with self.db.manager.engine.connect() as conn:
                pending = (
                    conn.execute(
                        text(
                            "SELECT * FROM orders WHERE purpose='EXIT' AND state IN ('CREATED','SENT','PARTIAL')"
                        )
                    )
                    .mappings()
                    .all()
                )

            for order in pending:
                broker_order_id = str(order.get("broker_order_id", ""))
                if not broker_order_id:
                    continue
                try:
                    status = self.broker.get_order_status(broker_order_id)
                    if status.state in ("FILLED", "CANCELLED", "REJECTED"):
                        self.db.update_order(
                            order["id"],
                            state=status.state,
                            filled_qty=status.filled_quantity,
                            avg_fill_price=status.average_fill_price,
                        )
                        if status.state == "FILLED":
                            position_id = order.get("position_id")
                            if position_id:
                                from bist_bot.agent.position_manager import PositionManager

                                pm = PositionManager(self.db, self.settings)
                                pm.close_position(
                                    position_id=position_id,
                                    exit_price=float(status.average_fill_price or 0),
                                    exit_reason=_parse_exit_reason(order.get("metadata_json")),
                                )
                except Exception:
                    logger.exception("pending_exit_check_failed", broker_order_id=broker_order_id)
        except Exception:
            logger.exception("process_pending_exits_failed")
