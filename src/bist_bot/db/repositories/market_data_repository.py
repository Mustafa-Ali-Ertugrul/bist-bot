"""Market-data persistence for the Faz 1 daily bars, universe and fundamentals."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select

from bist_bot.db.database import (
    BenchmarkBarRecord,
    DailyBarRecord,
    DatabaseManager,
    FundamentalRecord,
    InstrumentRecord,
    ScanResultRecord,
    ScreenSnapshotRecord,
)


@dataclass(frozen=True)
class DailyBar:
    date: date
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close_raw: float | None = None
    volume_tl: float | None = None
    market_cap_tl: float | None = None


@dataclass(frozen=True)
class Instrument:
    code: str
    ticker: str
    name: str
    sector: str | None


def _to_ticker(code: str) -> str:
    code = (code or "").strip().upper()
    return code if code.endswith(".IS") else f"{code}.IS"


class MarketDataRepository:
    """Idempotent writes: a re-run of the same sessions never duplicates rows."""

    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    # ------------------------------------------------------------------
    # Universe
    # ------------------------------------------------------------------
    def upsert_instruments(self, rows: Iterable[Instrument]) -> int:
        items = list(rows)
        if not items:
            return 0

        def _write(session):
            now = datetime.now(UTC)
            seen: set[str] = set()
            for item in items:
                code = item.code.strip().upper()
                if not code:
                    continue
                seen.add(code)
                record = session.get(InstrumentRecord, code)
                if record is None:
                    session.add(
                        InstrumentRecord(
                            code=code,
                            ticker=_to_ticker(code),
                            name=item.name.strip(),
                            sector=(item.sector or None),
                            market="BIST",
                            is_active=True,
                            first_seen=now,
                            last_seen=now,
                        )
                    )
                else:
                    record.ticker = _to_ticker(code)
                    record.name = item.name.strip() or record.name
                    record.sector = (item.sector or None) or record.sector
                    record.is_active = True
                    record.last_seen = now
            # A code missing from the vendor list is delisted/paused: keep the
            # row (history, position references) but stop syncing it.
            for record in session.scalars(select(InstrumentRecord)).all():
                if record.code not in seen:
                    record.is_active = False
            return len(seen)

        return int(self.manager.run_session(_write))

    def list_active_instruments(self) -> list[Instrument]:
        def _read(session):
            rows = session.scalars(
                select(InstrumentRecord)
                .where(InstrumentRecord.is_active.is_(True))
                .order_by(InstrumentRecord.code)
            ).all()
            return [
                Instrument(
                    code=r.code,
                    ticker=r.ticker,
                    name=r.name,
                    sector=r.sector,
                )
                for r in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def list_instruments(self) -> list[Instrument]:
        def _read(session):
            rows = session.scalars(select(InstrumentRecord).order_by(InstrumentRecord.code)).all()
            return [
                Instrument(code=r.code, ticker=r.ticker, name=r.name, sector=r.sector) for r in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def get_instrument(self, code: str) -> Instrument | None:
        normalized = (code or "").strip().upper().removesuffix(".IS")

        def _read(session):
            row = session.get(InstrumentRecord, normalized)
            if row is None:
                return None
            return Instrument(code=row.code, ticker=row.ticker, name=row.name, sector=row.sector)

        return self.manager.run_session(_read, read_only=True)

    def search_instruments(self, query: str, limit: int = 20) -> list[Instrument]:
        term = f"%{(query or '').strip().upper()}%"

        def _read(session):
            rows = session.scalars(
                select(InstrumentRecord)
                .where(
                    InstrumentRecord.is_active.is_(True),
                    (InstrumentRecord.code.like(term)) | (InstrumentRecord.name.ilike(term)),
                )
                .order_by(InstrumentRecord.code)
                .limit(max(1, min(limit, 50)))
            ).all()
            return [
                Instrument(code=r.code, ticker=r.ticker, name=r.name, sector=r.sector) for r in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    # ------------------------------------------------------------------
    # Daily bars
    # ------------------------------------------------------------------
    def write_bars(self, ticker: str, bars: Sequence[DailyBar], *, source: str) -> int:
        """Replace the bar rows for the given ticker inside the batch's date span."""
        if not bars:
            return 0
        start = min(b.date for b in bars)
        end = max(b.date for b in bars)

        def _write(session):
            session.execute(
                delete(DailyBarRecord).where(
                    DailyBarRecord.ticker == ticker,
                    DailyBarRecord.date >= start,
                    DailyBarRecord.date <= end,
                )
            )
            now = datetime.now(UTC)
            for bar in bars:
                session.add(
                    DailyBarRecord(
                        ticker=ticker,
                        date=bar.date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        close_raw=bar.close_raw,
                        volume_tl=bar.volume_tl,
                        market_cap_tl=bar.market_cap_tl,
                        source=source,
                        updated_at=now,
                    )
                )
            return len(bars)

        return int(self.manager.run_session(_write))

    def latest_bar_date(self, ticker: str) -> date | None:
        def _read(session):
            return session.scalar(
                select(DailyBarRecord.date)
                .where(DailyBarRecord.ticker == ticker)
                .order_by(DailyBarRecord.date.desc())
                .limit(1)
            )

        return self.manager.run_session(_read, read_only=True)

    def get_bars(
        self,
        ticker: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[DailyBar]:
        def _read(session):
            stmt = select(DailyBarRecord).where(DailyBarRecord.ticker == ticker)
            if start is not None:
                stmt = stmt.where(DailyBarRecord.date >= start)
            if end is not None:
                stmt = stmt.where(DailyBarRecord.date <= end)
            if limit is not None:
                stmt = stmt.order_by(DailyBarRecord.date.desc()).limit(limit)
                rows = list(session.scalars(stmt).all())[::-1]
            else:
                stmt = stmt.order_by(DailyBarRecord.date)
                rows = list(session.scalars(stmt).all())
            return [
                DailyBar(
                    date=r.date,
                    close=r.close,
                    open=r.open,
                    high=r.high,
                    low=r.low,
                    close_raw=r.close_raw,
                    volume_tl=r.volume_tl,
                    market_cap_tl=r.market_cap_tl,
                )
                for r in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def bar_count(self) -> int:
        def _read(session):
            return session.query(DailyBarRecord).count()

        return int(self.manager.run_session(_read, read_only=True))

    # ------------------------------------------------------------------
    # Fundamentals
    # ------------------------------------------------------------------
    def write_statements(
        self,
        ticker: str,
        statements: dict[str, dict[str, float]],
        *,
        source: str = "isyatirim",
    ) -> int:
        """Replace the statement rows for every period present in the payload."""
        if not statements:
            return 0
        periods = sorted(statements)

        def _write(session):
            session.execute(
                delete(FundamentalRecord).where(
                    FundamentalRecord.ticker == ticker,
                    FundamentalRecord.period.in_(periods),
                )
            )
            now = datetime.now(UTC)
            written = 0
            for period in periods:
                for item_code, value in statements[period].items():
                    session.add(
                        FundamentalRecord(
                            ticker=ticker,
                            period=period,
                            item_code=str(item_code),
                            value=float(value),
                            source=source,
                            updated_at=now,
                        )
                    )
                    written += 1
            return written

        return int(self.manager.run_session(_write))

    def get_latest_statements(self, ticker: str) -> dict[str, dict[str, float]]:
        def _read(session):
            rows = session.scalars(
                select(FundamentalRecord).where(FundamentalRecord.ticker == ticker)
            ).all()
            out: dict[str, dict[str, float]] = {}
            for row in rows:
                out.setdefault(row.period, {})[row.item_code] = row.value
            return out

        return dict(self.manager.run_session(_read, read_only=True))

    def get_all_statements(self) -> dict[str, dict[str, dict[str, float]]]:
        """All stored statements in one query: {ticker: {period: {item: value}}}."""

        def _read(session):
            rows = session.scalars(select(FundamentalRecord)).all()
            out: dict[str, dict[str, dict[str, float]]] = {}
            for row in rows:
                out.setdefault(row.ticker, {}).setdefault(row.period, {})[row.item_code] = row.value
            return out

        return dict(self.manager.run_session(_read, read_only=True))

    # ------------------------------------------------------------------
    # Screens (Faz 2)
    # ------------------------------------------------------------------
    def replace_scan_results(
        self,
        scan_id: str,
        as_of: date,
        rows: Sequence[tuple[str, float, str]],
    ) -> int:
        """Replace one screen's results for one session; earlier sessions stay."""

        def _write(session):
            session.execute(
                delete(ScanResultRecord).where(
                    ScanResultRecord.scan_id == scan_id,
                    ScanResultRecord.as_of == as_of,
                )
            )
            now = datetime.now(UTC)
            for ticker, value, detail in rows:
                session.add(
                    ScanResultRecord(
                        scan_id=scan_id,
                        as_of=as_of,
                        ticker=ticker,
                        value=float(value),
                        detail=str(detail)[:500],
                        updated_at=now,
                    )
                )
            return len(rows)

        return int(self.manager.run_session(_write))

    def get_scan_results(self, scan_id: str, as_of: date | None = None) -> list[dict[str, object]]:
        def _read(session):
            stmt = select(ScanResultRecord).where(ScanResultRecord.scan_id == scan_id)
            if as_of is not None:
                stmt = stmt.where(ScanResultRecord.as_of == as_of)
            else:
                latest = session.scalar(
                    select(ScanResultRecord.as_of)
                    .where(ScanResultRecord.scan_id == scan_id)
                    .order_by(ScanResultRecord.as_of.desc())
                    .limit(1)
                )
                if latest is None:
                    return []
                stmt = stmt.where(ScanResultRecord.as_of == latest)
            stmt = stmt.order_by(ScanResultRecord.ticker)
            return [
                {
                    "scan_id": row.scan_id,
                    "as_of": row.as_of.isoformat(),
                    "ticker": row.ticker,
                    "value": row.value,
                    "detail": row.detail,
                }
                for row in session.scalars(stmt).all()
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def get_scan_hits_for_ticker(self, ticker: str, *, days: int = 30) -> list[dict[str, object]]:
        """Recent screen hits for one ticker, newest first."""

        def _read(session):
            rows = session.scalars(
                select(ScanResultRecord)
                .where(ScanResultRecord.ticker == ticker)
                .order_by(ScanResultRecord.as_of.desc(), ScanResultRecord.scan_id)
                .limit(max(1, min(days * 8, 500)))
            ).all()
            if not rows:
                return []
            cutoff = max(row.as_of for row in rows) - timedelta(days=max(1, days))
            return [
                {
                    "scan_id": row.scan_id,
                    "as_of": row.as_of.isoformat(),
                    "value": row.value,
                    "detail": row.detail,
                }
                for row in rows
                if row.as_of >= cutoff
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def latest_market_date(self) -> date | None:
        """Latest session with any stored bar (used to gate screen runs)."""

        def _read(session):
            return session.scalar(
                select(DailyBarRecord.date).order_by(DailyBarRecord.date.desc()).limit(1)
            )

        return self.manager.run_session(_read, read_only=True)

    # ------------------------------------------------------------------
    # Screener snapshots (Faz 4)
    # ------------------------------------------------------------------
    def write_snapshots(self, as_of: date, rows: Sequence[dict[str, object]]) -> int:
        """Replace one session's snapshot rows (idempotent per day)."""

        def _write(session):
            session.execute(delete(ScreenSnapshotRecord).where(ScreenSnapshotRecord.as_of == as_of))
            now = datetime.now(UTC)
            for row in rows:
                session.add(
                    ScreenSnapshotRecord(
                        ticker=str(row["ticker"]),
                        as_of=as_of,
                        close=float(row["close"]),
                        change_pct=_as_float(row.get("change_pct")),
                        ret_1m=_as_float(row.get("ret_1m")),
                        ret_3m=_as_float(row.get("ret_3m")),
                        ret_1y=_as_float(row.get("ret_1y")),
                        rsi14=_as_float(row.get("rsi14")),
                        sma50_gap_pct=_as_float(row.get("sma50_gap_pct")),
                        sma200_gap_pct=_as_float(row.get("sma200_gap_pct")),
                        from_52w_high_pct=_as_float(row.get("from_52w_high_pct")),
                        avg_volume_20=_as_float(row.get("avg_volume_20")),
                        market_cap_tl=_as_float(row.get("market_cap_tl")),
                        pe_ttm=_as_float(row.get("pe_ttm")),
                        pb=_as_float(row.get("pb")),
                        net_margin_pct=_as_float(row.get("net_margin_pct")),
                        roe_pct=_as_float(row.get("roe_pct")),
                        sales_growth_yoy_pct=_as_float(row.get("sales_growth_yoy_pct")),
                        fundamentals_period=(
                            str(row["fundamentals_period"])
                            if row.get("fundamentals_period")
                            else None
                        ),
                        updated_at=now,
                    )
                )
            return len(rows)

        return int(self.manager.run_session(_write))

    def get_snapshots(self, as_of: date | None = None) -> list[dict[str, object]]:
        def _read(session):
            target = as_of
            if target is None:
                target = session.scalar(
                    select(ScreenSnapshotRecord.as_of)
                    .order_by(ScreenSnapshotRecord.as_of.desc())
                    .limit(1)
                )
            if target is None:
                return []
            rows = session.scalars(
                select(ScreenSnapshotRecord)
                .where(ScreenSnapshotRecord.as_of == target)
                .order_by(ScreenSnapshotRecord.ticker)
            ).all()
            return [
                {
                    "ticker": row.ticker,
                    "as_of": row.as_of.isoformat(),
                    "close": row.close,
                    "change_pct": row.change_pct,
                    "ret_1m": row.ret_1m,
                    "ret_3m": row.ret_3m,
                    "ret_1y": row.ret_1y,
                    "rsi14": row.rsi14,
                    "sma50_gap_pct": row.sma50_gap_pct,
                    "sma200_gap_pct": row.sma200_gap_pct,
                    "from_52w_high_pct": row.from_52w_high_pct,
                    "avg_volume_20": row.avg_volume_20,
                    "market_cap_tl": row.market_cap_tl,
                    "pe_ttm": row.pe_ttm,
                    "pb": row.pb,
                    "net_margin_pct": row.net_margin_pct,
                    "roe_pct": row.roe_pct,
                    "sales_growth_yoy_pct": row.sales_growth_yoy_pct,
                    "fundamentals_period": row.fundamentals_period,
                }
                for row in rows
            ]

        return list(self.manager.run_session(_read, read_only=True))

    def list_snapshot_dates(self, limit: int = 60) -> list[dict[str, object]]:
        def _read(session):
            rows = session.execute(
                select(
                    ScreenSnapshotRecord.as_of,
                    func.count(ScreenSnapshotRecord.ticker),
                )
                .group_by(ScreenSnapshotRecord.as_of)
                .order_by(ScreenSnapshotRecord.as_of.desc())
                .limit(max(1, min(limit, 400)))
            ).all()
            return [{"as_of": row[0].isoformat(), "count": int(row[1])} for row in rows]

        return list(self.manager.run_session(_read, read_only=True))

    def count_scan_results(self, as_of: date | None = None) -> dict[str, int]:
        def _read(session):
            target = as_of
            if target is None:
                target = session.scalar(
                    select(ScanResultRecord.as_of).order_by(ScanResultRecord.as_of.desc()).limit(1)
                )
            if target is None:
                return {}
            rows = session.execute(
                select(ScanResultRecord.scan_id, func.count(ScanResultRecord.ticker))
                .where(ScanResultRecord.as_of == target)
                .group_by(ScanResultRecord.scan_id)
            ).all()
            return {str(row[0]): int(row[1]) for row in rows}

        return dict(self.manager.run_session(_read, read_only=True))

    def list_scan_dates(self, limit: int = 60) -> list[str]:
        def _read(session):
            rows = session.scalars(
                select(ScanResultRecord.as_of)
                .distinct()
                .order_by(ScanResultRecord.as_of.desc())
                .limit(max(1, min(limit, 400)))
            ).all()
            return [row.isoformat() for row in rows]

        return list(self.manager.run_session(_read, read_only=True))

    # ------------------------------------------------------------------
    # Benchmarks (Faz 5)
    # ------------------------------------------------------------------
    def write_benchmark_bars(
        self, code: str, rows: list[tuple[date, float]], *, source: str
    ) -> int:
        if not rows:
            return 0
        start = min(row[0] for row in rows)
        end = max(row[0] for row in rows)

        def _write(session):
            session.execute(
                delete(BenchmarkBarRecord).where(
                    BenchmarkBarRecord.code == code,
                    BenchmarkBarRecord.date >= start,
                    BenchmarkBarRecord.date <= end,
                )
            )
            now = datetime.now(UTC)
            for bar_date, value in rows:
                session.add(
                    BenchmarkBarRecord(
                        code=code,
                        date=bar_date,
                        value=float(value),
                        source=source,
                        updated_at=now,
                    )
                )
            return len(rows)

        return int(self.manager.run_session(_write))

    def get_benchmark_bars(
        self, code: str, *, start: date | None = None
    ) -> list[tuple[date, float]]:
        def _read(session):
            stmt = select(BenchmarkBarRecord).where(BenchmarkBarRecord.code == code)
            if start is not None:
                stmt = stmt.where(BenchmarkBarRecord.date >= start)
            rows = session.scalars(stmt.order_by(BenchmarkBarRecord.date)).all()
            return [(row.date, row.value) for row in rows]

        return list(self.manager.run_session(_read, read_only=True))

    def latest_benchmark_date(self, code: str) -> date | None:
        def _read(session):
            return session.scalar(
                select(BenchmarkBarRecord.date)
                .where(BenchmarkBarRecord.code == code)
                .order_by(BenchmarkBarRecord.date.desc())
                .limit(1)
            )

        return self.manager.run_session(_read, read_only=True)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
