from datetime import datetime

from sqlalchemy import select

from db.database import PaperTradeRecord
from db.repositories import AppRepository


class SignalDatabase(AppRepository):
    def close_paper_trade(self, trade_id, close_price, close_reason):
        with self.manager.session_scope() as session:
            trade = session.scalar(
                select(PaperTradeRecord)
                .where(PaperTradeRecord.id == trade_id)
                .limit(1)
            )
            if trade is None:
                return
            trade.close_price = close_price
            trade.close_reason = close_reason
            trade.close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trade.outcome = "CLOSED"


__all__ = ["SignalDatabase"]
