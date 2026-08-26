import sqlite3

c = sqlite3.connect("/app/data/bist_signals.db")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("tables:", tables)
for t in ("signals", "scan_log", "users", "orders", "paper_trades"):
    if t in tables:
        print(t, "count:", c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
print("last signals:", c.execute("SELECT ticker, signal_type, score, created_at FROM signals ORDER BY id DESC LIMIT 5").fetchall())