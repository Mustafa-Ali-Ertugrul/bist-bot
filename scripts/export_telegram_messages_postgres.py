"""Replay last-week Telegram messages from Postgres using the real notifier code.

Run INSIDE the bist-bot-worker container (has bist_bot package + psycopg2 + settings).
Usage: python export_telegram_messages_postgres.py
"""
import io
import json
import sys
from datetime import datetime, timezone

import psycopg2

sys.path.insert(0, "/app/src")

from bist_bot.strategy.signal_models import Signal, SignalType
from bist_bot.notifier import TelegramNotifier
from bist_bot.strategy.engine_filters import is_trade_actionable
from bist_bot.strategy.params import StrategyParams

DB_DSN = "postgresql://bist:bist@postgres:5432/bist_bot"
SINCE = "2026-08-12"
OUT = "/app/results/telegram_messages_last_week_postgres.md"

# Conservative profile matching the live radar strategy (STRATEGY_PROFILE=conservative).
params = StrategyParams.conservative()

conn = psycopg2.connect(DB_DSN)
cur = conn.cursor()
cur.execute(
    """
    SELECT timestamp, ticker, signal_type, score, price, stop_loss, target_price,
           position_size, confidence, reasons, conditions, score_breakdown, created_at
    FROM signals
    WHERE DATE(created_at) BETWEEN %s AND CURRENT_DATE
    ORDER BY created_at ASC
    """,
    (SINCE,),
)
rows = cur.fetchall()
conn.close()

notifier = TelegramNotifier(sender=lambda **kw: True)  # never sends, only builds
ticker_names = {}

buf = io.StringIO()
buf.write(f"# Telegram Bildirimleri (gerçek veri) — {SINCE} → bugün\n\n")

sent_detail = 0
for r in rows:
    (
        ts, ticker, signal_type, score, price, stop_loss, target_price,
        pos_size, confidence, reasons_raw, conditions_raw, sb_raw, created_at,
    ) = r
    reasons = []
    if conditions_raw:
        try:
            reasons = [str(x) for x in json.loads(conditions_raw)]
        except Exception:
            reasons = [s.strip() for s in str(reasons_raw or "").split("|") if s.strip()]
    elif reasons_raw:
        reasons = [s.strip() for s in str(reasons_raw).split("|") if s.strip()]

    score_breakdown = None
    if sb_raw:
        try:
            parsed = json.loads(sb_raw)
            if isinstance(parsed, dict) and parsed and "by_reason" not in parsed:
                score_breakdown = {k: float(v) for k, v in parsed.items() if isinstance(v, (int, float))}
        except Exception:
            score_breakdown = None

    signal = Signal(
        ticker=ticker,
        signal_type=SignalType.from_value(signal_type),
        score=float(score),
        price=float(price),
        stop_loss=float(stop_loss or 0),
        target_price=float(target_price or 0),
        position_size=int(pos_size) if pos_size is not None else None,
        confidence=str(confidence or "confidence.low"),
        timestamp=ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts,
        reasons=reasons,
        score_breakdown=score_breakdown,
    )
    # Recompute the directional actionable flag with the conservative profile
    # (the same contract the engine uses) so the rendered labels match reality.
    signal.buy_threshold = params.buy_threshold
    signal.sell_threshold = params.sell_threshold
    signal.is_actionable = is_trade_actionable(signal, params)
    try:
        msg = notifier._build_signal_message(signal)
    except Exception as e:
        msg = f"BUILD_ERROR: {e}"
    tag = "✅ DETAY MESAJI (score>0)" if float(score) > 0 else "ℹ️ scan_summary içinde"
    if float(score) > 0:
        sent_detail += 1
    buf.write(f"\n## {ticker} | {signal_type} | skor={score} | {created_at}\n\n```\n{msg}\n```\n---\n")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())

print(f"WROTE {OUT}: {len(rows)} sinyal ({sent_detail} detay mesajı)")