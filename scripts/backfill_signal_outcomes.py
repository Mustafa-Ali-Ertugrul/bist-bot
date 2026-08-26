"""A2 — Signal outcome backfill (PENDING temizligi + provenance).

Classifies every PENDING signal in Postgres:

- Radar / non-actionable / geometry-eksik actionable → ``NOT_TRACKED``
  (bilincli: NOT_TRACKED ≠ LOSS; asla kayip sayilmaz).
- Actionable + gecerli geometry → ``SignalReplayEngine`` ile gelecek gunluk
  barlar uzerinde puanlanir (look-ahead guvenli: giris sinyal gununden
  sonraki ilk barin acilisi; TP/SL ayni barda carpisirsa SL once).
  Sonuc: ``TARGET_HIT`` / ``STOP_HIT`` / ``TIMEOUT``.
- Degerlendirme penceresi henuz tamamlanmamis (yeterli gelecek bar yok,
  data_ended timeout) → ``WINDOW_OPEN``: PENDING birakilir, sonraki
  calistirmada barlar gelince puanlanir.
- Bars hic cekilememis → ``NO_DATA``: PENDING birakilir, raporlanir.

Provenance: backfill sonuctemel ``outcome_source='backfill_daily'`` ve
``backfilled_at`` ile isaretlenir; canli tracker 'live_tracker' yazar.
Semantik fark (gunluk-bar T+1 vs canli intraday) kalibrasyonda
``outcome_source`` filtresiyle ayristirilir.

Usage:
    python scripts/backfill_signal_outcomes.py --db URL            # dry-run
    python scripts/backfill_signal_outcomes.py --db URL --apply
    python scripts/backfill_signal_outcomes.py --db URL --bars-dir csv/
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bist_bot.backtest.signal_replay import (
    ReplaySignal,
    SignalReplayEngine,
    build_cost_scenarios,
    normalize_bars,
)
from bist_bot.db.database import SignalRecord
from bist_bot.strategy.params import StrategyParams

SOURCE_BACKFILL = "backfill_daily"
EXIT_REASON_MAP = {"TP": "TARGET_HIT", "SL": "STOP_HIT", "TIMEOUT": "TIMEOUT"}


def _row_to_replay_signal(row) -> ReplaySignal:
    ts = row.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ReplaySignal(
        id=row.id,
        ticker=row.ticker,
        timestamp=ts,
        signal_type=row.signal_type,
        score=float(row.score) if row.score is not None else None,
        price=float(row.price or 0.0),
        stop_loss=float(row.stop_loss) if row.stop_loss is not None else None,
        target_price=float(row.target_price) if row.target_price is not None else None,
        confidence=row.confidence,
    )


def _direction_aware_profit_pct(signal: ReplaySignal, entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0
    if signal.direction == "short":
        return round((entry - exit_price) / entry * 100, 2)
    return round((exit_price - entry) / entry * 100, 2)


def classify_signals(
    signals: list[ReplaySignal],
    bars_by_ticker: dict[str, pd.DataFrame],
    engine: SignalReplayEngine | None = None,
    params: StrategyParams | None = None,
) -> list[dict]:
    """Pure classification+replay; no DB access (test edilebilir)."""
    engine = engine or SignalReplayEngine(timeout_bars=5, cost_models=build_cost_scenarios())
    params = params or StrategyParams()
    decisions: list[dict] = []

    for s in signals:
        base = {"id": s.id, "ticker": s.ticker, "signal_type": s.signal_type, "score": s.score}
        if not s.is_actionable(params):
            decisions.append({**base, "decision": "NOT_TRACKED", "reason": "not_actionable"})
            continue
        valid, reason = s.validate_geometry()
        if not valid:
            decisions.append({**base, "decision": "NOT_TRACKED", "reason": reason})
            continue
        bars = bars_by_ticker.get(s.ticker)
        if bars is None or bars.empty:
            decisions.append({**base, "decision": "NO_DATA", "reason": "no_bars"})
            continue
        trade, skip = engine.simulate_single_signal(s, bars, cost_model_name="base")
        if trade is None:
            if skip in ("skipped_no_next_bar", "skipped_no_entry_bar"):
                decisions.append({**base, "decision": "WINDOW_OPEN", "reason": skip})
            else:  # gap_through_stop/target → giris olusmadi, degerlenemez
                decisions.append({**base, "decision": "NOT_TRACKED", "reason": skip})
            continue
        if trade.data_ended and trade.exit_reason == "TIMEOUT":
            # Pencere tamamlanmadi (veri bitti) → sonraki calistirmada tekrar
            decisions.append({**base, "decision": "WINDOW_OPEN", "reason": "window_incomplete"})
            continue
        decisions.append(
            {
                **base,
                "decision": "SCORED",
                "outcome": EXIT_REASON_MAP[trade.exit_reason],
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "profit_pct": _direction_aware_profit_pct(s, trade.entry_price, trade.exit_price),
                "bars_held": trade.bars_held,
            }
        )
    return decisions


def load_pending_signals(engine: sa.engine.Engine, ticker: str | None = None) -> list[ReplaySignal]:
    # ORM Session kullan: Core Connection uzerinde select(Entity) bu Surumde
    # PK kolonunu donduruyor, entity'yi degil.
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        stmt = sa.select(SignalRecord).where(SignalRecord.outcome == "PENDING")
        if ticker:
            stmt = stmt.where(SignalRecord.ticker == ticker)
        rows = session.scalars(stmt.order_by(SignalRecord.id.asc())).all()
    return [_row_to_replay_signal(r) for r in rows]


def load_bars(tickers: list[str], period: str = "1y", interval: str = "1d",
              bars_dir: str | None = None) -> dict[str, pd.DataFrame]:
    bars: dict[str, pd.DataFrame] = {}
    if bars_dir:
        base = Path(bars_dir)
        for t in tickers:
            csv = base / f"{t}.csv"
            if csv.exists():
                df = normalize_bars(pd.read_csv(csv))
                if df is not None and not df.empty:
                    bars[t] = df
        return bars
    from bist_bot.data.fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    for t in sorted(set(tickers)):
        try:
            df = fetcher.fetch_single(t, period=period, interval=interval)
        except Exception:
            continue
        df = normalize_bars(df)
        if df is not None and not df.empty:
            bars[t] = df
    return bars


def apply_decisions(engine: sa.engine.Engine, decisions: list[dict]) -> dict[str, int]:
    """SCORED + NOT_TRACKED yazilir; WINDOW_OPEN/NO_DATA PENDING kalir."""
    written = Counter()
    now = datetime.now(UTC)
    with engine.begin() as conn:
        for d in decisions:
            if d["decision"] == "SCORED":
                conn.execute(
                    sa.update(SignalRecord)
                    .where(SignalRecord.id == d["id"])
                    .values(
                        outcome=d["outcome"],
                        outcome_price=d["exit_price"],
                        outcome_date=now,
                        profit_pct=d["profit_pct"],
                        outcome_source=SOURCE_BACKFILL,
                        backfilled_at=now,
                    )
                )
                written["SCORED"] += 1
            elif d["decision"] == "NOT_TRACKED":
                conn.execute(
                    sa.update(SignalRecord)
                    .where(SignalRecord.id == d["id"])
                    .values(
                        outcome="NOT_TRACKED",
                        outcome_date=now,
                        outcome_source=SOURCE_BACKFILL,
                        backfilled_at=now,
                    )
                )
                written["NOT_TRACKED"] += 1
    return dict(written)


def ensure_provenance_columns(engine: sa.engine.Engine) -> str:
    """create_all mevcut tabloya kolon eklemez → Postgres'te ALTER TABLE."""
    if engine.dialect.name != "postgresql":
        return "SKIP (postgres degil)"
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS outcome_source TEXT"))
        conn.execute(sa.text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS backfilled_at TIMESTAMP"))
    return "OK: outcome_source + backfilled_at hazir"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", required=True, help="SQLAlchemy URL (Postgres)")
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--period", default="1y")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--bars-dir", default=None)
    parser.add_argument("--report", default="results/backfill_outcome_raporu.md")
    args = parser.parse_args()

    engine = sa.create_engine(args.db)
    print(ensure_provenance_columns(engine))

    signals = load_pending_signals(engine, args.ticker)
    print(f"PENDING sinyal: {len(signals)}")

    needed = sorted({s.ticker for s in signals if s.is_actionable(StrategyParams())})
    print(f"Bars cekiliyor: {len(needed)} ticker...")
    bars = load_bars(needed, period=args.period, interval=args.interval, bars_dir=args.bars_dir)
    print(f"Bars hazir: {len(bars)}/{len(needed)}")

    decisions = classify_signals(signals, bars)
    counts = Counter(d["decision"] for d in decisions)
    print("Siniflandirma:", dict(counts))

    written = {}
    if args.apply:
        written = apply_decisions(engine, decisions)
        print("Yazilan:", written)

    scored = [d for d in decisions if d["decision"] == "SCORED"]
    wins = sum(1 for d in scored if d["profit_pct"] > 0)
    lines = [
        "# A2 — Outcome Backfill Raporu",
        "",
        f"Tarih: {datetime.now(UTC).strftime('%d.%m.%Y %H:%M UTC')} · Mod: "
        f"{'APPLY' if args.apply else 'DRY-RUN'}",
        "",
        "## Siniflandirma",
        "",
        "| Karar | Adet | Anlam |",
        "|---|---|---|",
        f"| SCORED_BACKFILL | {counts.get('SCORED', 0)} | Replay ile puanlandi (outcome_source=backfill_daily) |",
        f"| NOT_TRACKED | {counts.get('NOT_TRACKED', 0)} | Radar / non-actionable / giris olusmadi |",
        f"| WINDOW_OPEN | {counts.get('WINDOW_OPEN', 0)} | Pencere acik; PENDING birakildi, tekrar kosulur |",
        f"| NO_DATA | {counts.get('NO_DATA', 0)} | Bars yok; PENDING birakildi |",
        "",
        "## Puanlanan Sinyaller",
        "",
        f"- Toplam: {len(scored)} · Kazanan: {wins} "
        f"(kazanma orani {100.0 * wins / len(scored):.1f}%)" if scored else "- Puanlanan sinyal yok.",
        "",
        "> **Semantik notu:** Backfill sonuctemel gunluk-bar T+1 semantigi tasir",
        "> (giris = sinyal sonrasi ilk bar acilisi; cikis = kalici stop/hedef).",
        "> Canli tracker intraday semantigi kullanir. Ayni alanlarda saklanirlar",
        "> ama `outcome_source` ile ayristirilirlar; kalibrasyon filtresi",
        "> `outcome_source='live_tracker'` kullanmalidir.",
    ]
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rapor: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
