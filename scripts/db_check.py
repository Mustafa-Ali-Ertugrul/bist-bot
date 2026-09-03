import os
import sqlite3
import sys

# Container path by default; override via argv[1] or DB_PATH for local runs.
db_path = (
    sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "/app/data/bist_signals.db")
)
if not os.path.exists(db_path):
    raise SystemExit(f"Database not found: {db_path} (pass path as argv[1] or set DB_PATH)")
print("db:", db_path)
c = sqlite3.connect(db_path)
tables = [
    r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
]
print("tables:", tables)
for t in ("signals", "scan_log", "users", "orders", "paper_trades"):
    if t in tables:
        print(t, "count:", c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
print(
    "last signals:",
    c.execute(
        "SELECT ticker, signal_type, score, created_at FROM signals ORDER BY id DESC LIMIT 5"
    ).fetchall(),
)
