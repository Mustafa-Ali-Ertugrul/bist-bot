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
            
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {config.PAPER_TRADES_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    signal_price REAL NOT NULL,
                    signal_time TEXT NOT NULL,
                    close_price REAL,
                    score INTEGER,
                    regime TEXT,
                    filled_at REAL,
                    outcome TEXT DEFAULT 'OPEN',
                    actual_profit_pct REAL
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

    def add_paper_trade(
        self,
        ticker: str,
        signal_type: str,
        signal_price: float,
        signal_time: str = None,
        score: int = 0,
        regime: str = "UNKNOWN",
    ):
        signal_time = signal_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""INSERT INTO {config.PAPER_TRADES_TABLE}
                   (ticker, signal_type, signal_price, signal_time, score, regime)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    signal_type,
                    signal_price,
                    signal_time,
                    score,
                    regime,
                ),
            )
            conn.commit()

    def update_paper_close(self, ticker: str, close_price: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""UPDATE {config.PAPER_TRADES_TABLE}
                   SET close_price = ?, outcome = 'CLOSED',
                   actual_profit_pct = (signal_price - close_price) / signal_price * 100
                   WHERE ticker = ? AND outcome = 'OPEN'
                   ORDER BY id DESC LIMIT 1""",
                (close_price, ticker),
            )
            conn.commit()

    def update_all_paper_close(self, prices: dict):
        for ticker, close_price in prices.items():
            self.update_paper_close(ticker, close_price)

    def get_open_paper_trades(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                f"""SELECT * FROM {config.PAPER_TRADES_TABLE} 
                   WHERE outcome = 'OPEN'"""
            ).fetchall()

    def close_paper_trade(
        self,
        ticker: str,
        exit_price: float,
        exit_date: str,
        actual_profit_pct: float = None,
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""UPDATE {config.PAPER_TRADES_TABLE}
                   SET exit_price = ?, exit_date = ?, outcome = 'CLOSED', actual_profit_pct = ?
                   WHERE ticker = ? AND outcome = 'OPEN'
                   ORDER BY id DESC LIMIT 1""",
                (exit_price, exit_date, actual_profit_pct, ticker),
            )
            conn.commit()

    def get_paper_performance(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            trades = conn.execute(
                f"""SELECT * FROM {config.PAPER_TRADES_TABLE} WHERE outcome = 'CLOSED'"""
            ).fetchall()
            
            if not trades:
                return {}
            
            profitable = sum(1 for t in trades if t[10] and t[10] > 0)
            total = len(trades)
            avg_profit = sum(t[10] for t in trades if t[10]) / total if total > 0 else 0
        
        return {
            "total_trades": total,
            "profitable": profitable,
            "win_rate": round(profitable / total * 100, 1) if total > 0 else 0,
            "avg_profit_pct": round(avg_profit, 2),
        }
