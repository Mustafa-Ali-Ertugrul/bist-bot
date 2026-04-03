import sqlite3
from datetime import datetime
from typing import Optional
import logging

import config
from strategy import Signal, SignalType

logger = logging.getLogger(__name__)


class SignalDatabase:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    score REAL NOT NULL,
                    price REAL NOT NULL,
                    stop_loss REAL,
                    target_price REAL,
                    confidence TEXT,
                    reasons TEXT,
                    outcome TEXT DEFAULT 'PENDING',
                    outcome_price REAL,
                    outcome_date TEXT,
                    profit_pct REAL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_scanned INTEGER,
                    signals_generated INTEGER,
                    buy_signals INTEGER,
                    sell_signals INTEGER
                )
            """)

            conn.commit()
        logger.info(f"📂 Veritabanı hazır: {self.db_path}")

    def save_signal(self, signal: Signal):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO signals
                (timestamp, ticker, signal_type, score, price,
                 stop_loss, target_price, confidence, reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.timestamp.isoformat(),
                signal.ticker,
                signal.signal_type.value,
                signal.score,
                signal.price,
                signal.stop_loss,
                signal.target_price,
                signal.confidence,
                " | ".join(signal.reasons),
            ))
            conn.commit()
        logger.info(f"  💾 Sinyal kaydedildi: {signal.ticker}")

    def save_scan_log(
        self,
        total: int,
        generated: int,
        buys: int,
        sells: int
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO scan_log
                (timestamp, total_scanned, signals_generated,
                 buy_signals, sell_signals)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                total, generated, buys, sells
            ))
            conn.commit()

    def get_latest_signal(self, ticker: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM signals
                WHERE ticker = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (ticker,)).fetchone()
        return dict(row) if row else None

    def get_latest_signal(self, ticker: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM signals
                WHERE ticker = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (ticker,)).fetchone()
        return dict(row) if row else None

    def get_recent_signals(
        self,
        limit: int = 50,
        ticker: str = None
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if ticker:
                rows = conn.execute("""
                    SELECT * FROM signals
                    WHERE ticker = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (ticker, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM signals
                    ORDER BY timestamp DESC LIMIT ?
                """, (limit,)).fetchall()

        return [dict(row) for row in rows]

    def update_outcome(
        self,
        signal_id: int,
        outcome: str,
        outcome_price: float
    ):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT price FROM signals WHERE id = ?",
                (signal_id,)
            ).fetchone()

            if row:
                original_price = row[0]
                profit_pct = (
                    (outcome_price - original_price) / original_price * 100
                )

                conn.execute("""
                    UPDATE signals
                    SET outcome = ?, outcome_price = ?,
                        outcome_date = ?, profit_pct = ?
                    WHERE id = ?
                """, (
                    outcome,
                    outcome_price,
                    datetime.now().isoformat(),
                    round(profit_pct, 2),
                    signal_id
                ))
                conn.commit()

    def get_performance_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM signals"
            ).fetchone()[0]

            completed = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE outcome != 'PENDING'"
            ).fetchone()[0]

            profitable = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE profit_pct > 0"
            ).fetchone()[0]

            avg_profit = conn.execute(
                "SELECT AVG(profit_pct) FROM signals WHERE profit_pct IS NOT NULL"
            ).fetchone()[0]

        return {
            "total_signals": total,
            "completed": completed,
            "profitable": profitable,
            "win_rate": round(
                profitable / completed * 100, 1
            ) if completed > 0 else 0,
            "avg_profit_pct": round(avg_profit, 2) if avg_profit else 0,
        }
