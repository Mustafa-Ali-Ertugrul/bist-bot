"""Stored-signal replay engine (Faz 2).

Replays the signals that were persisted to ``bist_signals.db`` over historical
daily bars in order to measure *exit* performance (TP / SL / TIMEOUT,
R-multiple, MFE / MAE) of signals the live bot actually produced.

Design contract (locked in the Faz 2 plan):

* **Read-only.** The database is only read through ``SignalsRepository``;
  nothing is written back. The indicator-driven :class:`Backtester` is not
  touched — this module is a separate, additive measurement path.
* **Stored levels are never recomputed.** ``stop_loss`` / ``target_price`` come
  from the persisted signal row, exactly as the bot published them.
* **Conservative entry.** Daily bars cannot resolve intraday fills, so entry is
  the *open of the first trading bar after the signal timestamp*.
* **Evidence guard.** Any aggregate computed from fewer than
  :data:`MIN_SAMPLE_SIZE` trades is flagged ``low_n`` and may not be used to
  justify a threshold change.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.backtest.models import CostModel
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import SignalType

logger = get_logger(__name__, component="signal_replay")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TR_TZ = timezone(timedelta(hours=3))
"""Exchange timezone used to map a stored UTC timestamp onto a trading day."""

MIN_SAMPLE_SIZE = 10
"""Hard guard: aggregates below this trade count never produce a recommendation."""

DEFAULT_TIMEOUT_BARS = 5
DEFAULT_NOTIONAL_TL = 10_000.0
DEFAULT_HISTORY_PERIOD = "2y"
DEFAULT_HISTORY_INTERVAL = "1d"

LONG = "long"
SHORT = "short"

OUTCOME_TP = "TP"
OUTCOME_SL = "SL"
OUTCOME_TIMEOUT = "TIMEOUT"

DATASET_RAW = "raw"
DATASET_EPISODES = "episodes"
DATASET_FIRST_ACTIONABLE = "first_actionable"
DATASET_HYSTERESIS = "hysteresis"
DATASETS = (DATASET_RAW, DATASET_EPISODES, DATASET_FIRST_ACTIONABLE, DATASET_HYSTERESIS)

BUY_TYPES = frozenset({SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY})
SELL_TYPES = frozenset({SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL})

REQUIRED_BAR_COLUMNS = ("open", "high", "low", "close")

#: Cost scenarios reuse the shared :class:`CostModel`. ``stress`` mirrors the
#: convention already used by ``scripts/run_wf_cost_stress.py``
#: (commission 5 bps, slippage 15 bps).
COST_SCENARIOS: dict[str, CostModel] = {
    "zero": CostModel(
        commission_bps=0.0,
        bsmv_bps=0.0,
        exchange_fee_bps=0.0,
        slippage_model="fixed",
        fixed_slippage_bps=0.0,
    ),
    "base": CostModel(slippage_model="fixed"),
    "stress": CostModel(
        commission_bps=5.0,
        bsmv_bps=0.1,
        exchange_fee_bps=0.3,
        slippage_model="fixed",
        fixed_slippage_bps=15.0,
    ),
}

#: Score buckets are applied to ``abs(score)`` so long and short sides use the
#: same edges (short side is the mirror of the long side).
SCORE_BUCKET_EDGES: tuple[tuple[str, float, float], ...] = (
    ("0-8", 0.0, 8.0),
    ("8-20", 8.0, 20.0),
    ("20-25", 20.0, 25.0),
    ("25+", 25.0, math.inf),
)

SKIP_INVALID_GEOMETRY = "invalid_geometry"
SKIP_NO_BARS = "no_bars"
SKIP_NO_NEXT_BAR = "skipped_no_next_bar"
SKIP_INSUFFICIENT_BARS = "insufficient_bars"
SKIP_BAD_TIMESTAMP = "bad_timestamp"
SKIP_BAD_PRICE = "bad_price"


# ---------------------------------------------------------------------------
# Signal model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplaySignal:
    """A persisted signal, normalized for replay."""

    ticker: str
    signal_type: SignalType
    direction: str
    score: float
    price: float
    stop_loss: float
    target_price: float
    confidence: str
    timestamp: datetime
    signal_id: int | None = None
    episode_index: int = 0
    episode_position: int = 0
    episode_size: int = 1

    @property
    def risk_per_share(self) -> float:
        return abs(self.price - self.stop_loss)

    @property
    def planned_rr(self) -> float:
        risk = self.risk_per_share
        if risk <= 0:
            return 0.0
        return abs(self.target_price - self.price) / risk

    @property
    def trading_day(self) -> pd.Timestamp:
        """Exchange-local calendar day the signal belongs to."""
        return pd.Timestamp(self.timestamp.astimezone(TR_TZ).date())

    def is_actionable(self, buy_threshold: float) -> bool:
        """Symmetric actionability (Faz 1H, karar D1).

        HOLD / RADAR are never trade-actionable. The long side reuses the engine
        contract (``score >= buy_threshold``); the short side mirrors it on the
        absolute score.

        Note: Faz 1H ships ``engine_filters.is_trade_actionable`` with exactly
        this semantic. This module keeps a local copy so the replay engine does
        not depend on Faz 1H landing first; swap it for the shared helper once
        Faz 1H is merged.
        """
        if self.signal_type in (SignalType.HOLD, SignalType.RADAR):
            return False
        if self.signal_type in BUY_TYPES:
            return self.score >= buy_threshold
        if self.signal_type in SELL_TYPES:
            return abs(self.score) >= buy_threshold
        return False


@dataclass(frozen=True)
class SkippedSignal:
    ticker: str
    timestamp: str
    signal_type: str
    score: float
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Loading / normalization
# ---------------------------------------------------------------------------


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _parse_timestamp(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def resolve_direction(price: float, stop_loss: float, target_price: float) -> str | None:
    """Infer trade direction from the stored level geometry.

    ``stop < price < target`` is a long plan, ``stop > price > target`` is the
    Faz 1H short plan geometry. Anything else (missing or crossed levels) is
    rejected as ``invalid_geometry``.
    """
    if price <= 0 or stop_loss <= 0 or target_price <= 0:
        return None
    if stop_loss < price < target_price:
        return LONG
    if stop_loss > price > target_price:
        return SHORT
    return None


def signals_from_rows(
    rows: Iterable[dict[str, Any]],
) -> tuple[list[ReplaySignal], list[SkippedSignal]]:
    """Normalize repository rows into :class:`ReplaySignal` objects."""
    signals: list[ReplaySignal] = []
    skipped: list[SkippedSignal] = []

    for row in rows:
        ticker = str(row.get("ticker", "") or "")
        raw_type = str(row.get("signal_type", "") or "")
        score = _to_float(row.get("score"))
        timestamp = _parse_timestamp(row.get("timestamp"))
        if timestamp is None:
            skipped.append(
                SkippedSignal(
                    ticker=ticker,
                    timestamp=str(row.get("timestamp", "")),
                    signal_type=raw_type,
                    score=score,
                    reason=SKIP_BAD_TIMESTAMP,
                )
            )
            continue
        try:
            signal_type = SignalType.from_value(raw_type)
        except ValueError:
            skipped.append(
                SkippedSignal(
                    ticker=ticker,
                    timestamp=timestamp.isoformat(),
                    signal_type=raw_type,
                    score=score,
                    reason=SKIP_BAD_PRICE,
                    detail="unknown signal type",
                )
            )
            continue

        price = _to_float(row.get("price"))
        stop_loss = _to_float(row.get("stop_loss"))
        target_price = _to_float(row.get("target_price"))
        direction = resolve_direction(price, stop_loss, target_price)
        if direction is None:
            skipped.append(
                SkippedSignal(
                    ticker=ticker,
                    timestamp=timestamp.isoformat(),
                    signal_type=raw_type,
                    score=score,
                    reason=SKIP_INVALID_GEOMETRY,
                    detail=f"price={price} stop={stop_loss} target={target_price}",
                )
            )
            continue

        signals.append(
            ReplaySignal(
                ticker=ticker,
                signal_type=signal_type,
                direction=direction,
                score=score,
                price=price,
                stop_loss=stop_loss,
                target_price=target_price,
                confidence=str(row.get("confidence", "") or ""),
                timestamp=timestamp,
                signal_id=row.get("id") if isinstance(row.get("id"), int) else None,
            )
        )

    signals.sort(key=lambda item: (item.ticker, item.timestamp))
    return signals, skipped


def load_stored_signals(
    repository: Any | None = None,
    *,
    limit: int = 10_000,
    ticker: str | None = None,
    db_path: str | None = None,
) -> tuple[list[ReplaySignal], list[SkippedSignal]]:
    """Read persisted signals (read-only) and normalize them for replay.

    ``db_path`` targets an explicit SQLite file; by default the configured
    database (``settings.DB_PATH`` → ``bist_signals.db``) is used.
    """
    if repository is None:
        from bist_bot.db.repositories.signals_repository import SignalsRepository

        if db_path:
            from bist_bot.db.database import DatabaseManager

            repository = SignalsRepository(manager=DatabaseManager(sqlite_path=db_path))
        else:
            repository = SignalsRepository()
    rows = repository.get_signals(limit=limit, ticker=ticker)
    return signals_from_rows(rows)


# ---------------------------------------------------------------------------
# Dataset builders
# ---------------------------------------------------------------------------


def build_episodes(signals: Sequence[ReplaySignal]) -> list[list[ReplaySignal]]:
    """Group consecutive same-type signals of one ticker into episodes."""
    episodes: list[list[ReplaySignal]] = []
    ordered = sorted(signals, key=lambda item: (item.ticker, item.timestamp))
    current: list[ReplaySignal] = []
    for signal in ordered:
        if current and (
            current[-1].ticker == signal.ticker and current[-1].signal_type == signal.signal_type
        ):
            current.append(signal)
            continue
        if current:
            episodes.append(current)
        current = [signal]
    if current:
        episodes.append(current)
    return episodes


def _stamp_episode(members: Sequence[ReplaySignal], episode_index: int) -> list[ReplaySignal]:
    from dataclasses import replace

    size = len(members)
    return [
        replace(member, episode_index=episode_index, episode_position=position, episode_size=size)
        for position, member in enumerate(members)
    ]


def build_dataset(
    signals: Sequence[ReplaySignal],
    dataset: str,
    *,
    buy_threshold: float | None = None,
) -> list[ReplaySignal]:
    """Return the signal subset for ``dataset``.

    * ``raw`` — every valid stored signal.
    * ``episodes`` — first signal of each consecutive same-type run.
    * ``first_actionable`` — first *actionable* signal of each episode
      (episodes without one are dropped).
    * ``hysteresis`` — second signal of each episode (2 consecutive
      confirmations), episodes of size 1 are dropped.
    """
    if dataset not in DATASETS:
        raise ValueError(f"Unknown dataset: {dataset}")

    if buy_threshold is None:
        buy_threshold = float(StrategyParams.from_settings().buy_threshold)

    episodes = build_episodes(signals)
    selected: list[ReplaySignal] = []
    for episode_index, members in enumerate(episodes):
        stamped = _stamp_episode(members, episode_index)
        if dataset == DATASET_RAW:
            selected.extend(stamped)
        elif dataset == DATASET_EPISODES:
            selected.append(stamped[0])
        elif dataset == DATASET_FIRST_ACTIONABLE:
            actionable = next(
                (item for item in stamped if item.is_actionable(buy_threshold)),
                None,
            )
            if actionable is not None:
                selected.append(actionable)
        elif dataset == DATASET_HYSTERESIS and len(stamped) >= 2:
            selected.append(stamped[1])

    selected.sort(key=lambda item: (item.ticker, item.timestamp))
    return selected


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

BarProvider = Callable[[str], "pd.DataFrame | None"]


def prepare_bars(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    """Validate/normalize a price frame and attach decision-time context columns."""
    if frame is None or frame.empty:
        return None
    bars = frame.copy()
    bars.columns = [str(col).lower() for col in bars.columns]
    if not all(column in bars.columns for column in REQUIRED_BAR_COLUMNS):
        return None
    if not isinstance(bars.index, pd.DatetimeIndex):
        index_source = None
        for key in ("date", "timestamp", "datetime"):
            if key in bars.columns:
                index_source = key
                break
        if index_source is None:
            return None
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars[index_source]))
        bars = bars.drop(columns=[index_source])
    if bars.index.tz is not None:
        bars.index = bars.index.tz_localize(None)
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()

    close = bars["close"].astype(float)
    if "ema_200" not in bars.columns:
        bars["ema_200"] = close.ewm(span=200, adjust=False).mean()
    if "rsi" not in bars.columns:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        bars["rsi"] = (100 - (100 / (1 + rs))).clip(0, 100)
    return bars


class FetcherBarProvider:
    """Cached ``BISTDataFetcher`` adapter (one fetch per ticker per run)."""

    def __init__(
        self,
        fetcher: Any | None = None,
        *,
        period: str = DEFAULT_HISTORY_PERIOD,
        interval: str = DEFAULT_HISTORY_INTERVAL,
    ) -> None:
        self._fetcher = fetcher
        self.period = period
        self.interval = interval
        self._cache: dict[str, pd.DataFrame | None] = {}

    def _ensure_fetcher(self) -> Any:
        if self._fetcher is None:
            from bist_bot.data.fetcher import BISTDataFetcher

            self._fetcher = BISTDataFetcher()
        return self._fetcher

    def __call__(self, ticker: str) -> pd.DataFrame | None:
        if ticker in self._cache:
            return self._cache[ticker]
        frame: pd.DataFrame | None
        try:
            frame = self._ensure_fetcher().fetch_single(
                ticker, period=self.period, interval=self.interval
            )
        except Exception as exc:  # pragma: no cover - network/provider failure
            logger.warning("signal_replay_fetch_failed", ticker=ticker, error=str(exc))
            frame = None
        prepared = prepare_bars(frame)
        self._cache[ticker] = prepared
        return prepared


def dict_bar_provider(frames: dict[str, pd.DataFrame]) -> BarProvider:
    """Build a provider from an in-memory ``{ticker: frame}`` mapping (tests)."""
    prepared = {ticker: prepare_bars(frame) for ticker, frame in frames.items()}

    def _provider(ticker: str) -> pd.DataFrame | None:
        return prepared.get(ticker)

    return _provider


def csv_bar_provider(directory: str | Path) -> BarProvider:
    """Read bars from ``<directory>/<TICKER>.csv`` instead of the network.

    Enables deterministic, offline re-runs of a replay (and CI smoke runs) from
    a snapshot of the price data. The CSV must have a date column/index plus
    ``open,high,low,close``.
    """
    root = Path(directory)
    cache: dict[str, pd.DataFrame | None] = {}

    def _provider(ticker: str) -> pd.DataFrame | None:
        if ticker in cache:
            return cache[ticker]
        candidates = [root / f"{ticker}.csv", root / f"{ticker.replace('.IS', '')}.csv"]
        path = next((item for item in candidates if item.exists()), None)
        if path is None:
            cache[ticker] = None
            return None
        try:
            frame = pd.read_csv(path, index_col=0, parse_dates=True)
        except (OSError, ValueError) as exc:
            logger.warning("signal_replay_csv_read_failed", ticker=ticker, error=str(exc))
            frame = None
        cache[ticker] = prepare_bars(frame)
        return cache[ticker]

    return _provider


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayConfig:
    timeout_bars: int = DEFAULT_TIMEOUT_BARS
    entry_delay_bars: int = 1
    cost_scenario: str = "base"
    notional_tl: float = DEFAULT_NOTIONAL_TL
    min_sample_size: int = MIN_SAMPLE_SIZE

    def cost_model(self) -> CostModel:
        if self.cost_scenario not in COST_SCENARIOS:
            raise ValueError(f"Unknown cost scenario: {self.cost_scenario}")
        return COST_SCENARIOS[self.cost_scenario]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_bars": self.timeout_bars,
            "entry_delay_bars": self.entry_delay_bars,
            "cost_scenario": self.cost_scenario,
            "notional_tl": self.notional_tl,
            "min_sample_size": self.min_sample_size,
        }


@dataclass
class ReplayTrade:
    ticker: str
    signal_type: str
    direction: str
    score: float
    confidence: str
    signal_time: str
    entry_date: str
    entry_price: float
    stop_loss: float
    target_price: float
    exit_date: str
    exit_price: float
    outcome: str
    exit_detail: str
    holding_bars: int
    risk_per_share: float
    planned_rr: float
    r_multiple: float
    net_r_multiple: float
    gross_return_pct: float
    net_return_pct: float
    mfe_r: float
    mae_r: float
    mfe_pct: float
    mae_pct: float
    gross_pnl_tl: float
    fees_tl: float
    slippage_tl: float
    net_pnl_tl: float
    cost_scenario: str
    dataset: str = ""
    episode_index: int = 0
    episode_position: int = 0
    episode_size: int = 1
    entry_close_vs_ema200: float | None = None
    above_ema200: bool | None = None
    rsi_at_signal: float | None = None

    @property
    def is_win(self) -> bool:
        return self.r_multiple > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReplayRun:
    trades: list[ReplayTrade] = field(default_factory=list)
    skipped: list[SkippedSignal] = field(default_factory=list)
    dataset: str = DATASET_RAW
    config: ReplayConfig = field(default_factory=ReplayConfig)

    @property
    def n(self) -> int:
        return len(self.trades)


def _bar_value(bar: pd.Series, key: str) -> float:
    return float(bar[key])


def _scan_exit(
    signal: ReplaySignal,
    window: pd.DataFrame,
) -> tuple[int, float, str, str] | None:
    """Find the exit bar for ``signal`` inside ``window``.

    Returns ``(offset, price, outcome, detail)`` or ``None`` when the position
    is still open at the end of the window.

    Rules (locked): gap through a level exits at that bar's open; if both stop
    and target are touched inside the same bar the stop is assumed first.
    """
    is_long = signal.direction == LONG
    stop = signal.stop_loss
    target = signal.target_price

    for offset in range(len(window)):
        bar = window.iloc[offset]
        bar_open = _bar_value(bar, "open")
        high = _bar_value(bar, "high")
        low = _bar_value(bar, "low")

        if offset > 0:
            # Gap handling only applies to bars after entry: on the entry bar
            # the open *is* the fill price.
            if is_long and bar_open <= stop:
                return offset, bar_open, OUTCOME_SL, "gap_open"
            if not is_long and bar_open >= stop:
                return offset, bar_open, OUTCOME_SL, "gap_open"
            if is_long and bar_open >= target:
                return offset, bar_open, OUTCOME_TP, "gap_open"
            if not is_long and bar_open <= target:
                return offset, bar_open, OUTCOME_TP, "gap_open"

        # Stop is evaluated before target inside the same bar (SL-first).
        if is_long:
            if low <= stop:
                return offset, stop, OUTCOME_SL, "intrabar"
            if high >= target:
                return offset, target, OUTCOME_TP, "intrabar"
        else:
            if high >= stop:
                return offset, stop, OUTCOME_SL, "intrabar"
            if low <= target:
                return offset, target, OUTCOME_TP, "intrabar"
    return None


def _excursions(
    signal: ReplaySignal, window: pd.DataFrame, entry_price: float
) -> tuple[float, float]:
    """Return ``(mfe, mae)`` as non-negative price magnitudes."""
    highest = float(window["high"].max())
    lowest = float(window["low"].min())
    if signal.direction == LONG:
        mfe = max(0.0, highest - entry_price)
        mae = max(0.0, entry_price - lowest)
    else:
        mfe = max(0.0, entry_price - lowest)
        mae = max(0.0, highest - entry_price)
    return mfe, mae


def _apply_costs(
    direction: str,
    entry_price: float,
    exit_price: float,
    *,
    cost_model: CostModel,
    notional_tl: float,
) -> tuple[float, float, float, float]:
    """Return ``(gross_pnl, fees, slippage_cost, net_pnl)`` in TL.

    The shared :class:`CostModel` is reused; the ``fixed`` slippage branch is
    used so replay numbers stay deterministic across runs.
    """
    if entry_price <= 0:
        return 0.0, 0.0, 0.0, 0.0
    shares = notional_tl / entry_price
    slip = cost_model.fixed_slippage_bps / 10_000.0
    fee_bps = cost_model.commission_bps + cost_model.bsmv_bps + cost_model.exchange_fee_bps
    fee_rate = fee_bps / 10_000.0

    if direction == LONG:
        entry_fill = entry_price * (1 + slip)
        exit_fill = exit_price * (1 - slip)
        gross_pnl = shares * (exit_price - entry_price)
        net_before_fees = shares * (exit_fill - entry_fill)
    else:
        entry_fill = entry_price * (1 - slip)
        exit_fill = exit_price * (1 + slip)
        gross_pnl = shares * (entry_price - exit_price)
        net_before_fees = shares * (entry_fill - exit_fill)

    fees = (shares * entry_fill + shares * exit_fill) * fee_rate
    slippage_cost = abs(gross_pnl - net_before_fees)
    net_pnl = net_before_fees - fees
    return gross_pnl, fees, slippage_cost, net_pnl


def replay_signal(
    signal: ReplaySignal,
    bars: pd.DataFrame | None,
    *,
    config: ReplayConfig | None = None,
    cost_model: CostModel | None = None,
) -> tuple[ReplayTrade | None, SkippedSignal | None]:
    """Replay one stored signal. Returns ``(trade, skip)`` with exactly one set."""
    config = config or ReplayConfig()
    cost_model = cost_model or config.cost_model()

    def _skip(reason: str, detail: str = "") -> tuple[None, SkippedSignal]:
        return None, SkippedSignal(
            ticker=signal.ticker,
            timestamp=signal.timestamp.isoformat(),
            signal_type=signal.signal_type.value,
            score=signal.score,
            reason=reason,
            detail=detail,
        )

    if bars is None or bars.empty:
        return _skip(SKIP_NO_BARS)
    if signal.risk_per_share <= 0:
        return _skip(SKIP_BAD_PRICE, "risk per share is zero")

    next_bar_pos = int(bars.index.searchsorted(signal.trading_day, side="right"))
    entry_idx = next_bar_pos + max(0, config.entry_delay_bars - 1)
    if entry_idx >= len(bars):
        return _skip(SKIP_NO_NEXT_BAR, f"signal_day={signal.trading_day.date()}")

    window = bars.iloc[entry_idx : entry_idx + config.timeout_bars]
    if window.empty:
        return _skip(SKIP_NO_NEXT_BAR)

    entry_price = float(window.iloc[0]["open"])
    if entry_price <= 0:
        return _skip(SKIP_BAD_PRICE, "non-positive entry open")

    found = _scan_exit(signal, window)
    if found is None:
        if len(window) < config.timeout_bars:
            return _skip(
                SKIP_INSUFFICIENT_BARS,
                f"only {len(window)} of {config.timeout_bars} bars available",
            )
        exit_offset = len(window) - 1
        exit_price = float(window.iloc[exit_offset]["close"])
        outcome = OUTCOME_TIMEOUT
        detail = "timeout_close"
    else:
        exit_offset, exit_price, outcome, detail = found

    held = window.iloc[: exit_offset + 1]
    mfe, mae = _excursions(signal, held, entry_price)

    signed_pnl_per_share = (
        exit_price - entry_price if signal.direction == LONG else entry_price - exit_price
    )
    risk = signal.risk_per_share
    gross_pnl, fees, slippage_cost, net_pnl = _apply_costs(
        signal.direction,
        entry_price,
        exit_price,
        cost_model=cost_model,
        notional_tl=config.notional_tl,
    )
    shares = config.notional_tl / entry_price
    risk_tl = shares * risk

    decision_bar = bars.iloc[entry_idx - 1] if entry_idx > 0 else None
    above_ema200: bool | None = None
    close_vs_ema200: float | None = None
    rsi_at_signal: float | None = None
    if decision_bar is not None:
        ema200 = float(decision_bar.get("ema_200", float("nan")))
        close = float(decision_bar["close"])
        if not math.isnan(ema200) and ema200 > 0:
            above_ema200 = close >= ema200
            close_vs_ema200 = round((close / ema200 - 1.0) * 100, 4)
        rsi_value = float(decision_bar.get("rsi", float("nan")))
        if not math.isnan(rsi_value):
            rsi_at_signal = round(rsi_value, 2)

    trade = ReplayTrade(
        ticker=signal.ticker,
        signal_type=signal.signal_type.value,
        direction=signal.direction,
        score=signal.score,
        confidence=signal.confidence,
        signal_time=signal.timestamp.isoformat(),
        entry_date=str(pd.Timestamp(window.index[0]).date()),
        entry_price=round(entry_price, 4),
        stop_loss=signal.stop_loss,
        target_price=signal.target_price,
        exit_date=str(pd.Timestamp(window.index[exit_offset]).date()),
        exit_price=round(exit_price, 4),
        outcome=outcome,
        exit_detail=detail,
        holding_bars=exit_offset + 1,
        risk_per_share=round(risk, 4),
        planned_rr=round(signal.planned_rr, 4),
        r_multiple=round(signed_pnl_per_share / risk, 4),
        net_r_multiple=round(net_pnl / risk_tl, 4) if risk_tl > 0 else 0.0,
        gross_return_pct=round(signed_pnl_per_share / entry_price * 100, 4),
        net_return_pct=round(net_pnl / config.notional_tl * 100, 4),
        mfe_r=round(mfe / risk, 4),
        mae_r=round(mae / risk, 4),
        mfe_pct=round(mfe / entry_price * 100, 4),
        mae_pct=round(mae / entry_price * 100, 4),
        gross_pnl_tl=round(gross_pnl, 2),
        fees_tl=round(fees, 2),
        slippage_tl=round(slippage_cost, 2),
        net_pnl_tl=round(net_pnl, 2),
        cost_scenario=config.cost_scenario,
        episode_index=signal.episode_index,
        episode_position=signal.episode_position,
        episode_size=signal.episode_size,
        entry_close_vs_ema200=close_vs_ema200,
        above_ema200=above_ema200,
        rsi_at_signal=rsi_at_signal,
    )
    return trade, None


def run_replay(
    signals: Sequence[ReplaySignal],
    bar_provider: BarProvider,
    *,
    config: ReplayConfig | None = None,
    dataset: str = DATASET_RAW,
) -> ReplayRun:
    """Replay every signal in ``signals`` and collect trades plus skip reasons."""
    config = config or ReplayConfig()
    cost_model = config.cost_model()
    run = ReplayRun(dataset=dataset, config=config)

    for signal in signals:
        bars = bar_provider(signal.ticker)
        trade, skip = replay_signal(signal, bars, config=config, cost_model=cost_model)
        if trade is not None:
            trade.dataset = dataset
            run.trades.append(trade)
        elif skip is not None:
            run.skipped.append(skip)

    logger.info(
        "signal_replay_completed",
        dataset=dataset,
        cost_scenario=config.cost_scenario,
        trades=len(run.trades),
        skipped=len(run.skipped),
    )
    return run


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def score_bucket_label(score: float) -> str:
    magnitude = abs(score)
    for label, low, high in SCORE_BUCKET_EDGES:
        if low <= magnitude < high:
            return label
    return SCORE_BUCKET_EDGES[-1][0]


def bucket_key(direction: str, score: float) -> str:
    return f"{direction}:{score_bucket_label(score)}"


def _mean(values: Sequence[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def _median(values: Sequence[float]) -> float:
    return round(statistics.median(values), 4) if values else 0.0


def summarize_trades(
    trades: Sequence[ReplayTrade], *, min_sample_size: int = MIN_SAMPLE_SIZE
) -> dict[str, Any]:
    """Aggregate a trade list. Always carries the ``low_n`` guard fields."""
    n = len(trades)
    r_values = [trade.r_multiple for trade in trades]
    net_r_values = [trade.net_r_multiple for trade in trades]
    outcomes: dict[str, int] = {OUTCOME_TP: 0, OUTCOME_SL: 0, OUTCOME_TIMEOUT: 0}
    for trade in trades:
        outcomes[trade.outcome] = outcomes.get(trade.outcome, 0) + 1
    wins = sum(1 for trade in trades if trade.is_win)
    low_n = n < min_sample_size
    return {
        "n": n,
        "low_n": low_n,
        "recommendation_allowed": not low_n,
        "min_sample_size": min_sample_size,
        "wins": wins,
        "losses": n - wins,
        "win_rate_pct": round(wins / n * 100, 2) if n else 0.0,
        "outcomes": outcomes,
        "tp_rate_pct": round(outcomes[OUTCOME_TP] / n * 100, 2) if n else 0.0,
        "sl_rate_pct": round(outcomes[OUTCOME_SL] / n * 100, 2) if n else 0.0,
        "timeout_rate_pct": round(outcomes[OUTCOME_TIMEOUT] / n * 100, 2) if n else 0.0,
        "avg_r": _mean(r_values),
        "median_r": _median(r_values),
        "total_r": round(sum(r_values), 4),
        "avg_net_r": _mean(net_r_values),
        "avg_gross_return_pct": _mean([trade.gross_return_pct for trade in trades]),
        "avg_net_return_pct": _mean([trade.net_return_pct for trade in trades]),
        "avg_mfe_r": _mean([trade.mfe_r for trade in trades]),
        "avg_mae_r": _mean([trade.mae_r for trade in trades]),
        "avg_holding_bars": _mean([float(trade.holding_bars) for trade in trades]),
        "avg_planned_rr": _mean([trade.planned_rr for trade in trades]),
    }


def _group(
    trades: Sequence[ReplayTrade], key: Callable[[ReplayTrade], str]
) -> dict[str, list[ReplayTrade]]:
    grouped: dict[str, list[ReplayTrade]] = {}
    for trade in trades:
        grouped.setdefault(key(trade), []).append(trade)
    return dict(sorted(grouped.items()))


def summarize_groups(
    trades: Sequence[ReplayTrade],
    key: Callable[[ReplayTrade], str],
    *,
    min_sample_size: int = MIN_SAMPLE_SIZE,
) -> dict[str, dict[str, Any]]:
    return {
        name: summarize_trades(members, min_sample_size=min_sample_size)
        for name, members in _group(trades, key).items()
    }


def score_bucket_summary(
    trades: Sequence[ReplayTrade], *, min_sample_size: int = MIN_SAMPLE_SIZE
) -> dict[str, dict[str, Any]]:
    return summarize_groups(
        trades,
        lambda trade: bucket_key(trade.direction, trade.score),
        min_sample_size=min_sample_size,
    )


def confidence_summary(
    trades: Sequence[ReplayTrade], *, min_sample_size: int = MIN_SAMPLE_SIZE
) -> dict[str, dict[str, Any]]:
    return summarize_groups(
        trades, lambda trade: trade.confidence or "unknown", min_sample_size=min_sample_size
    )


def ticker_summary(
    trades: Sequence[ReplayTrade], *, min_sample_size: int = MIN_SAMPLE_SIZE
) -> dict[str, dict[str, Any]]:
    return summarize_groups(trades, lambda trade: trade.ticker, min_sample_size=min_sample_size)


def _delta(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "n_delta": variant["n"] - baseline["n"],
        "win_rate_delta_pct": round(variant["win_rate_pct"] - baseline["win_rate_pct"], 2),
        "avg_r_delta": round(variant["avg_r"] - baseline["avg_r"], 4),
        "avg_net_r_delta": round(variant["avg_net_r"] - baseline["avg_net_r"], 4),
    }


def ema200_filter_analysis(
    trades: Sequence[ReplayTrade], *, min_sample_size: int = MIN_SAMPLE_SIZE
) -> dict[str, Any]:
    """Long signals below EMA200 at decision time are dropped; report the delta."""
    kept = [t for t in trades if not (t.direction == LONG and t.above_ema200 is False)]
    removed = [t for t in trades if t.direction == LONG and t.above_ema200 is False]
    unknown = [t for t in trades if t.above_ema200 is None]
    baseline = summarize_trades(trades, min_sample_size=min_sample_size)
    filtered = summarize_trades(kept, min_sample_size=min_sample_size)
    return {
        "rule": "drop long trades whose decision-bar close < EMA200",
        "baseline": baseline,
        "filtered": filtered,
        "removed": summarize_trades(removed, min_sample_size=min_sample_size),
        "unknown_context_trades": len(unknown),
        "delta": _delta(baseline, filtered),
    }


def rsi_extreme_analysis(
    trades: Sequence[ReplayTrade],
    *,
    overbought: float = 70.0,
    oversold: float = 30.0,
    min_sample_size: int = MIN_SAMPLE_SIZE,
) -> dict[str, Any]:
    """Veto long entries with RSI > 70 and short entries with RSI < 30."""

    def _vetoed(trade: ReplayTrade) -> bool:
        if trade.rsi_at_signal is None:
            return False
        if trade.direction == LONG:
            return trade.rsi_at_signal > overbought
        return trade.rsi_at_signal < oversold

    kept = [t for t in trades if not _vetoed(t)]
    removed = [t for t in trades if _vetoed(t)]
    baseline = summarize_trades(trades, min_sample_size=min_sample_size)
    filtered = summarize_trades(kept, min_sample_size=min_sample_size)
    return {
        "rule": f"veto long RSI>{overbought:.0f} / short RSI<{oversold:.0f} at decision bar",
        "baseline": baseline,
        "filtered": filtered,
        "removed": summarize_trades(removed, min_sample_size=min_sample_size),
        "unknown_context_trades": sum(1 for t in trades if t.rsi_at_signal is None),
        "delta": _delta(baseline, filtered),
    }


def entry_delay_analysis(
    signals: Sequence[ReplaySignal],
    bar_provider: BarProvider,
    *,
    config: ReplayConfig,
    delays: Sequence[int] = (1, 2, 3),
    dataset: str = DATASET_RAW,
) -> dict[str, Any]:
    """Re-run the replay with +1 / +2 / +3 bar entry delays."""
    from dataclasses import replace

    baseline_run = run_replay(
        signals, bar_provider, config=replace(config, entry_delay_bars=1), dataset=dataset
    )
    baseline = summarize_trades(baseline_run.trades, min_sample_size=config.min_sample_size)
    variants: dict[str, Any] = {}
    for delay in delays:
        run = run_replay(
            signals, bar_provider, config=replace(config, entry_delay_bars=delay), dataset=dataset
        )
        summary = summarize_trades(run.trades, min_sample_size=config.min_sample_size)
        variants[f"delay_{delay}"] = {
            "summary": summary,
            "skipped": len(run.skipped),
            "delta_vs_delay_1": _delta(baseline, summary),
        }
    return {"baseline_delay_bars": 1, "variants": variants}


def guard_report(
    bucket_summaries: dict[str, dict[str, Any]], *, min_sample_size: int = MIN_SAMPLE_SIZE
) -> dict[str, Any]:
    """Collect which buckets may (not) back a threshold recommendation."""
    eligible = sorted(name for name, s in bucket_summaries.items() if not s["low_n"])
    blocked = {name: s["n"] for name, s in sorted(bucket_summaries.items()) if s["low_n"]}
    return {
        "min_sample_size": min_sample_size,
        "eligible_buckets": eligible,
        "low_n_buckets": blocked,
        "threshold_change_recommended": False,
        "reason": (
            f"no bucket reached the N >= {min_sample_size} evidence guard; report-only outcome"
            if not eligible
            else "buckets passed the guard — manual review required before any threshold change"
        ),
    }


def signal_inventory(
    signals: Sequence[ReplaySignal], skipped: Sequence[SkippedSignal]
) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    by_ticker: dict[str, int] = {}
    for signal in signals:
        by_type[signal.signal_type.name] = by_type.get(signal.signal_type.name, 0) + 1
        by_direction[signal.direction] = by_direction.get(signal.direction, 0) + 1
        by_ticker[signal.ticker] = by_ticker.get(signal.ticker, 0) + 1
    skip_reasons: dict[str, int] = {}
    for item in skipped:
        skip_reasons[item.reason] = skip_reasons.get(item.reason, 0) + 1
    return {
        "valid_signals": len(signals),
        "rejected_signals": len(skipped),
        "by_signal_type": dict(sorted(by_type.items())),
        "by_direction": dict(sorted(by_direction.items())),
        "distinct_tickers": len(by_ticker),
        "rejection_reasons": dict(sorted(skip_reasons.items())),
        "first_signal": min((s.timestamp.isoformat() for s in signals), default=None),
        "last_signal": max((s.timestamp.isoformat() for s in signals), default=None),
    }


def analyze_run(run: ReplayRun) -> dict[str, Any]:
    """Full analysis block for a single dataset × cost replay run."""
    min_n = run.config.min_sample_size
    buckets = score_bucket_summary(run.trades, min_sample_size=min_n)
    skip_reasons: dict[str, int] = {}
    for item in run.skipped:
        skip_reasons[item.reason] = skip_reasons.get(item.reason, 0) + 1
    return {
        "overall": summarize_trades(run.trades, min_sample_size=min_n),
        "by_direction": summarize_groups(
            run.trades, lambda trade: trade.direction, min_sample_size=min_n
        ),
        "by_signal_type": summarize_groups(
            run.trades, lambda trade: trade.signal_type, min_sample_size=min_n
        ),
        "by_score_bucket": buckets,
        "by_confidence": confidence_summary(run.trades, min_sample_size=min_n),
        "by_ticker": ticker_summary(run.trades, min_sample_size=min_n),
        "ema200_filter": ema200_filter_analysis(run.trades, min_sample_size=min_n),
        "rsi_extreme_veto": rsi_extreme_analysis(run.trades, min_sample_size=min_n),
        "skipped": {"total": len(run.skipped), "by_reason": dict(sorted(skip_reasons.items()))},
        "guard": guard_report(buckets, min_sample_size=min_n),
    }


# ---------------------------------------------------------------------------
# Orchestration + output
# ---------------------------------------------------------------------------


def replay_matrix(
    signals: Sequence[ReplaySignal],
    bar_provider: BarProvider,
    *,
    datasets: Sequence[str] = (DATASET_RAW, DATASET_EPISODES, DATASET_FIRST_ACTIONABLE),
    cost_scenarios: Sequence[str] = ("zero", "base", "stress"),
    config: ReplayConfig | None = None,
    buy_threshold: float | None = None,
) -> tuple[dict[str, dict[str, ReplayRun]], dict[str, list[ReplaySignal]]]:
    """Run every ``dataset × cost`` combination. Returns ``(runs, dataset_signals)``."""
    from dataclasses import replace

    base_config = config or ReplayConfig()
    if buy_threshold is None:
        buy_threshold = float(StrategyParams.from_settings().buy_threshold)

    dataset_signals = {
        dataset: build_dataset(signals, dataset, buy_threshold=buy_threshold)
        for dataset in datasets
    }
    runs: dict[str, dict[str, ReplayRun]] = {}
    for dataset in datasets:
        runs[dataset] = {}
        for scenario in cost_scenarios:
            runs[dataset][scenario] = run_replay(
                dataset_signals[dataset],
                bar_provider,
                config=replace(base_config, cost_scenario=scenario),
                dataset=dataset,
            )
    return runs, dataset_signals


def build_summary(
    *,
    signals: Sequence[ReplaySignal],
    rejected: Sequence[SkippedSignal],
    runs: dict[str, dict[str, ReplayRun]],
    dataset_signals: dict[str, list[ReplaySignal]],
    config: ReplayConfig,
    buy_threshold: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the JSON summary payload."""
    datasets_block: dict[str, Any] = {}
    for dataset, per_cost in runs.items():
        datasets_block[dataset] = {
            "signal_count": len(dataset_signals.get(dataset, [])),
            "costs": {scenario: analyze_run(run) for scenario, run in per_cost.items()},
        }

    guard_flags = [
        block["costs"][scenario]["guard"]["eligible_buckets"]
        for block in datasets_block.values()
        for scenario in block["costs"]
    ]
    any_eligible = any(bool(item) for item in guard_flags)

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "stored_signals_sqlite",
        "config": {**config.to_dict(), "buy_threshold": buy_threshold},
        "signal_inventory": signal_inventory(signals, rejected),
        "datasets": datasets_block,
        "decision": {
            "threshold_change_recommended": False,
            "evidence_guard": f"N >= {config.min_sample_size}",
            "any_bucket_passed_guard": any_eligible,
            "note": (
                "Report-only: no bucket cleared the evidence guard."
                if not any_eligible
                else "Some buckets cleared the guard; a threshold change still needs "
                "explicit review — the replay never auto-recommends."
            ),
        },
    }
    if extra:
        payload.update(extra)
    return payload


def write_trades_csv(trades: Sequence[ReplayTrade], path: str | Path) -> Path:
    """Write all trades to CSV (one row per trade)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ReplayTrade.__dataclass_fields__.keys())
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.to_dict())
    return target


def write_summary_json(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
