"""Historical signal replay backtester and analytics.

Executes trade replays on persisted signals using historical OHLCV bars without
re-computing entry scores or TP/SL levels. Adheres to conservative exit semantics
(SL-first on same bar, gap rules, timeout) and strictly evaluates bucket-level
guard metrics (N >= 10) before generating recommendations.
"""

from __future__ import annotations

import zoneinfo
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from bist_bot.backtest.models import CostModel
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import SignalType

ISTANBUL_TZ = zoneinfo.ZoneInfo("Europe/Istanbul")

# Half-open bucket boundaries: [low, high)
SCORE_BUCKET_DEFS: list[tuple[str, float, float]] = [
    ("0-8", 0.0, 8.0),
    ("8-20", 8.0, 20.0),
    ("20-25", 20.0, 25.0),
    ("25+", 25.0, float("inf")),
]

CONFIDENCE_KEYS: list[str] = [
    "confidence.low",
    "confidence.medium",
    "confidence.high",
]


def _to_istanbul_date(dt: datetime | date | str | None) -> date | None:
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # Assume UTC if naive, or localize directly
            dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
        return dt.astimezone(ISTANBUL_TZ).date()
    return None


@dataclass
class ReplaySignal:
    id: int | str
    ticker: str
    timestamp: datetime
    signal_type: str
    score: float | None
    price: float
    stop_loss: float | None
    target_price: float | None
    confidence: str | None = None
    timeframe: str = "1d"
    reasons: list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def signal_date(self) -> date:
        d = _to_istanbul_date(self.timestamp)
        return d if d is not None else self.timestamp.date()

    @property
    def direction(self) -> str | None:
        try:
            st = SignalType.from_value(self.signal_type)
        except ValueError:
            st = None
        if st is not None:
            if st.is_buy:
                return "long"
            if st.is_sell:
                return "short"
            return None
        # Fallback: substring matching on raw stored text
        raw = self.signal_type.upper()
        if any(w in raw for w in ["BUY", "AL"]):
            return "long"
        if any(w in raw for w in ["SELL", "SAT"]):
            return "short"
        return None

    @property
    def is_radar(self) -> bool:
        try:
            return SignalType.from_value(self.signal_type) is SignalType.RADAR
        except ValueError:
            raw = self.signal_type.upper()
            return "RADAR" in raw or "İZLE" in raw or "IZLE" in raw

    def validate_geometry(self) -> tuple[bool, str]:
        if self.is_radar:
            return False, "is_radar"
        if self.stop_loss is None or self.target_price is None:
            return False, "missing_geometry"
        if self.stop_loss <= 0 or self.target_price <= 0 or self.price <= 0:
            return False, "missing_geometry"

        d = self.direction
        if d == "long":
            if not (self.stop_loss < self.price < self.target_price):
                return False, "invalid_geometry"
        elif d == "short":
            if not (self.stop_loss > self.price > self.target_price):
                return False, "invalid_geometry"
        else:
            return False, "invalid_geometry"

        return True, "ok"

    def is_actionable(self, params: StrategyParams | None = None) -> bool:
        if self.is_radar or self.score is None:
            return False
        p = params or StrategyParams()
        d = self.direction
        if d == "long":
            return p.buy_actionable_score(self.score)
        if d == "short":
            return p.sell_actionable_score(self.score)
        return False


@dataclass
class ReplayTrade:
    signal_id: int | str
    ticker: str
    direction: str
    signal_type: str
    signal_score: float | None
    confidence: str | float | None
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    planned_stop: float
    planned_target: float
    exit_reason: str  # "TP", "SL", "TIMEOUT"
    gross_pnl_pct: float
    net_pnl_pct: float
    r_multiple_gross: float
    r_multiple_net: float
    mfe_pct: float
    mae_pct: float
    mfe_r: float
    mae_r: float
    bars_held: int
    data_ended: bool
    cost_model_name: str
    dataset_name: str
    total_cost_bps: float
    rr_setup: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_cost_scenarios() -> dict[str, CostModel]:
    return {
        "zero": CostModel(
            commission_bps=0.0,
            stamp_tax_bps=0.0,
            bsmv_bps=0.0,
            exchange_fee_bps=0.0,
            spread_bps=0.0,
            fixed_slippage_bps=0.0,
        ),
        "base": CostModel(
            commission_bps=2.0,
            stamp_tax_bps=9.3,
            bsmv_bps=5.0,
            exchange_fee_bps=0.3,
            spread_bps=10.0,
            fixed_slippage_bps=5.0,
        ),
        "stress": CostModel(
            commission_bps=5.0,
            stamp_tax_bps=9.3,
            bsmv_bps=5.0,
            exchange_fee_bps=0.3,
            spread_bps=15.0,
            fixed_slippage_bps=15.0,
        ),
    }


def normalize_bars(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    out = df.copy()
    if getattr(out.columns, "nlevels", 1) > 1:
        out.columns = [
            c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in out.columns
        ]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename: dict[str, str] = {}
    for c in list(out.columns):
        if c in {"adj close", "adj_close"}:
            rename[c] = "close"
    if rename:
        out = out.rename(columns=rename)
    req = {"open", "high", "low", "close"}
    if not req.issubset(set(out.columns)):
        return None

    # Normalise date column / index
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.date
    elif isinstance(out.index, pd.DatetimeIndex):
        out["date"] = out.index.date
    else:
        try:
            out["date"] = pd.to_datetime(out.index).date
        except Exception:
            return None

    out = out.sort_values("date").reset_index(drop=True)
    return out


# Dataset Builders
def build_dataset_raw(signals: Sequence[ReplaySignal]) -> list[ReplaySignal]:
    """Raw dataset: removes identical-day duplicates (same ticker, direction, signal_date)."""
    seen: set[tuple[str, str | None, date]] = set()
    out: list[ReplaySignal] = []
    # Sort chronologically
    sorted_sigs = sorted(signals, key=lambda s: s.timestamp)
    for sig in sorted_sigs:
        key = (sig.ticker, sig.direction, sig.signal_date)
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out


def build_dataset_episodes(
    signals: Sequence[ReplaySignal],
    bars_by_ticker: dict[str, pd.DataFrame] | None = None,
    max_gap_bars: int = 5,
) -> list[ReplaySignal]:
    """Episodes dataset: collapses consecutive signals of same ticker and direction into 1st signal.

    RADAR signals do not participate in episodes.
    """
    raw_sigs = build_dataset_raw(signals)
    by_ticker: dict[str, list[ReplaySignal]] = {}
    for s in raw_sigs:
        if s.is_radar:
            continue
        by_ticker.setdefault(s.ticker, []).append(s)

    out: list[ReplaySignal] = []
    for ticker, sig_list in by_ticker.items():
        sig_list.sort(key=lambda s: s.timestamp)
        current_ep_dir: str | None = None
        last_sig_date: date | None = None

        bars = bars_by_ticker.get(ticker) if bars_by_ticker else None
        bar_dates = list(bars["date"]) if bars is not None and "date" in bars.columns else []

        for sig in sig_list:
            if current_ep_dir != sig.direction:
                # New episode started
                out.append(sig)
                current_ep_dir = sig.direction
                last_sig_date = sig.signal_date
            else:
                # Check gap
                is_gap_exceeded = False
                if last_sig_date is not None and bar_dates:
                    try:
                        i1 = next(i for i, d in enumerate(bar_dates) if d >= last_sig_date)
                        i2 = next(i for i, d in enumerate(bar_dates) if d >= sig.signal_date)
                        if (i2 - i1) > max_gap_bars:
                            is_gap_exceeded = True
                    except StopIteration:
                        pass

                if is_gap_exceeded:
                    out.append(sig)
                    current_ep_dir = sig.direction
                    last_sig_date = sig.signal_date
                else:
                    # Still in same episode -> skip subsequent
                    last_sig_date = sig.signal_date

    out.sort(key=lambda s: s.timestamp)
    return out


def build_dataset_first_actionable(
    signals: Sequence[ReplaySignal],
    bars_by_ticker: dict[str, pd.DataFrame] | None = None,
    max_gap_bars: int = 5,
    params: StrategyParams | None = None,
) -> list[ReplaySignal]:
    """First-actionable dataset: 1st actionable signal per episode."""
    p = params or StrategyParams()
    raw_sigs = build_dataset_raw(signals)
    by_ticker: dict[str, list[ReplaySignal]] = {}
    for s in raw_sigs:
        if s.is_radar:
            continue
        by_ticker.setdefault(s.ticker, []).append(s)

    out: list[ReplaySignal] = []
    for ticker, sig_list in by_ticker.items():
        sig_list.sort(key=lambda s: s.timestamp)
        bars = bars_by_ticker.get(ticker) if bars_by_ticker else None
        bar_dates = list(bars["date"]) if bars is not None and "date" in bars.columns else []

        # Group into episode slices
        episodes: list[list[ReplaySignal]] = []
        current_ep: list[ReplaySignal] = []

        for sig in sig_list:
            if not current_ep:
                current_ep.append(sig)
            else:
                last_sig = current_ep[-1]
                if last_sig.direction != sig.direction:
                    episodes.append(current_ep)
                    current_ep = [sig]
                else:
                    is_gap_exceeded = False
                    if bar_dates:
                        try:
                            i1 = next(
                                i for i, d in enumerate(bar_dates) if d >= last_sig.signal_date
                            )
                            i2 = next(i for i, d in enumerate(bar_dates) if d >= sig.signal_date)
                            if (i2 - i1) > max_gap_bars:
                                is_gap_exceeded = True
                        except StopIteration:
                            pass
                    if is_gap_exceeded:
                        episodes.append(current_ep)
                        current_ep = [sig]
                    else:
                        current_ep.append(sig)
        if current_ep:
            episodes.append(current_ep)

        for ep in episodes:
            for s in ep:
                if s.is_actionable(p):
                    out.append(s)
                    break

    out.sort(key=lambda s: s.timestamp)
    return out


class SignalReplayEngine:
    def __init__(
        self,
        timeout_bars: int = 5,
        cost_models: dict[str, CostModel] | None = None,
    ) -> None:
        self.timeout_bars = timeout_bars
        self.cost_models = cost_models or build_cost_scenarios()

    def simulate_single_signal(
        self,
        signal: ReplaySignal,
        bars: pd.DataFrame,
        cost_model_name: str = "base",
        dataset_name: str = "raw",
        entry_delay_bars: int = 0,
    ) -> tuple[ReplayTrade | None, str]:
        valid, reason = signal.validate_geometry()
        if not valid:
            return None, reason

        if bars is None or len(bars) == 0:
            return None, "no_bars"

        sig_date = signal.signal_date
        bar_dates = list(bars["date"])

        # Find first tradable bar strictly AFTER signal date
        future_indices = [i for i, d in enumerate(bar_dates) if d > sig_date]
        if not future_indices:
            return None, "skipped_no_next_bar"

        base_entry_idx = future_indices[0]
        actual_entry_idx = base_entry_idx + entry_delay_bars

        if actual_entry_idx >= len(bars):
            return None, "skipped_no_entry_bar"

        entry_bar = bars.iloc[actual_entry_idx]
        entry_price = float(entry_bar["open"])
        direction = signal.direction or "long"
        stop_loss = float(signal.stop_loss)  # type: ignore[arg-type]
        target_price = float(signal.target_price)  # type: ignore[arg-type]

        # Check entry-bar gap condition: if open is already beyond level -> skip
        if direction == "long":
            if entry_price <= stop_loss:
                return None, "skipped_gap_through_stop"
            if entry_price >= target_price:
                return None, "skipped_gap_through_target"
        elif direction == "short":
            if entry_price >= stop_loss:
                return None, "skipped_gap_through_stop"
            if entry_price <= target_price:
                return None, "skipped_gap_through_target"

        # Scanning loop for exit
        exit_reason: str | None = None
        exit_price: float = 0.0
        exit_idx: int = actual_entry_idx
        data_ended = False

        scan_end_idx = actual_entry_idx + self.timeout_bars
        highs: list[float] = []
        lows: list[float] = []

        for cur_idx in range(actual_entry_idx, scan_end_idx):
            if cur_idx >= len(bars):
                # Data ended prematurely before timeout
                data_ended = True
                exit_idx = len(bars) - 1
                exit_price = float(bars.iloc[exit_idx]["close"])
                exit_reason = "TIMEOUT"
                break

            bar = bars.iloc[cur_idx]
            b_open = float(bar["open"])
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_close = float(bar["close"])

            highs.append(b_high)
            lows.append(b_low)

            # In-position gap check for subsequent bars (cur_idx > actual_entry_idx)
            if cur_idx > actual_entry_idx:
                if direction == "long":
                    if b_open <= stop_loss:
                        exit_reason = "SL"
                        exit_price = b_open
                        exit_idx = cur_idx
                        break
                    if b_open >= target_price:
                        exit_reason = "TP"
                        exit_price = b_open
                        exit_idx = cur_idx
                        break
                elif direction == "short":
                    if b_open >= stop_loss:
                        exit_reason = "SL"
                        exit_price = b_open
                        exit_idx = cur_idx
                        break
                    if b_open <= target_price:
                        exit_reason = "TP"
                        exit_price = b_open
                        exit_idx = cur_idx
                        break

            # Intrabar check
            if direction == "long":
                hit_sl = b_low <= stop_loss
                hit_tp = b_high >= target_price
                if hit_sl and hit_tp:
                    # SL FIRST rule
                    exit_reason = "SL"
                    exit_price = stop_loss
                    exit_idx = cur_idx
                    break
                elif hit_sl:
                    exit_reason = "SL"
                    exit_price = stop_loss
                    exit_idx = cur_idx
                    break
                elif hit_tp:
                    exit_reason = "TP"
                    exit_price = target_price
                    exit_idx = cur_idx
                    break
            elif direction == "short":
                hit_sl = b_high >= stop_loss
                hit_tp = b_low <= target_price
                if hit_sl and hit_tp:
                    # SL FIRST rule
                    exit_reason = "SL"
                    exit_price = stop_loss
                    exit_idx = cur_idx
                    break
                elif hit_sl:
                    exit_reason = "SL"
                    exit_price = stop_loss
                    exit_idx = cur_idx
                    break
                elif hit_tp:
                    exit_reason = "TP"
                    exit_price = target_price
                    exit_idx = cur_idx
                    break

            # If 5th bar (cur_idx == actual_entry_idx + self.timeout_bars - 1) and no exit -> TIMEOUT
            if cur_idx == actual_entry_idx + self.timeout_bars - 1:
                exit_reason = "TIMEOUT"
                exit_price = b_close
                exit_idx = cur_idx
                break

        if exit_reason is None:
            exit_reason = "TIMEOUT"
            exit_idx = min(scan_end_idx - 1, len(bars) - 1)
            exit_price = float(bars.iloc[exit_idx]["close"])

        # Holding duration: entry bar is bar 1
        bars_held = exit_idx - actual_entry_idx + 1

        # MFE / MAE calculations (inclusive of entry & exit bars)
        max_h = max(highs) if highs else entry_price
        min_l = min(lows) if lows else entry_price

        if direction == "long":
            gross_pnl_pct = (exit_price - entry_price) / entry_price
            mfe_pct = max(0.0, (max_h - entry_price) / entry_price)
            mae_pct = min(0.0, (min_l - entry_price) / entry_price)
            risk_per_share = abs(entry_price - stop_loss)
            pnl_per_share = exit_price - entry_price
            rr_setup = abs(target_price - entry_price) / max(1e-6, risk_per_share)
        else:
            gross_pnl_pct = (entry_price - exit_price) / entry_price
            mfe_pct = max(0.0, (entry_price - min_l) / entry_price)
            mae_pct = min(0.0, (entry_price - max_h) / entry_price)  # negative or 0
            risk_per_share = abs(stop_loss - entry_price)
            pnl_per_share = entry_price - exit_price
            rr_setup = abs(entry_price - target_price) / max(1e-6, risk_per_share)

        r_multiple_gross = pnl_per_share / max(1e-6, risk_per_share)
        mfe_r = (mfe_pct * entry_price) / max(1e-6, risk_per_share)
        mae_r = (mae_pct * entry_price) / max(1e-6, risk_per_share)

        # Cost deduction
        cm = self.cost_models.get(cost_model_name) or self.cost_models["base"]
        # Roundtrip cost in bps: 2*commission + 2*exchange_fee + stamp_tax + bsmv + 2*spread + 2*slippage
        roundtrip_bps = (
            2.0 * cm.commission_bps
            + 2.0 * cm.exchange_fee_bps
            + cm.stamp_tax_bps
            + cm.bsmv_bps
            + 2.0 * (cm.spread_bps / 2.0)
            + 2.0 * cm.fixed_slippage_bps
        )
        total_cost_pct = roundtrip_bps / 10000.0
        net_pnl_pct = gross_pnl_pct - total_cost_pct
        net_pnl_per_share = pnl_per_share - (total_cost_pct * entry_price)
        r_multiple_net = net_pnl_per_share / max(1e-6, risk_per_share)

        trade = ReplayTrade(
            signal_id=signal.id,
            ticker=signal.ticker,
            direction=direction,
            signal_type=signal.signal_type,
            signal_score=signal.score,
            confidence=signal.confidence,
            signal_date=str(sig_date),
            entry_date=str(bars.iloc[actual_entry_idx]["date"]),
            exit_date=str(bars.iloc[exit_idx]["date"]),
            entry_price=entry_price,
            exit_price=exit_price,
            planned_stop=stop_loss,
            planned_target=target_price,
            exit_reason=exit_reason,
            gross_pnl_pct=gross_pnl_pct,
            net_pnl_pct=net_pnl_pct,
            r_multiple_gross=r_multiple_gross,
            r_multiple_net=r_multiple_net,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            mfe_r=mfe_r,
            mae_r=mae_r,
            bars_held=bars_held,
            data_ended=data_ended,
            cost_model_name=cost_model_name,
            dataset_name=dataset_name,
            total_cost_bps=roundtrip_bps,
            rr_setup=rr_setup,
        )
        return trade, "ok"

    def replay_dataset(
        self,
        signals: Sequence[ReplaySignal],
        bars_by_ticker: dict[str, pd.DataFrame],
        cost_model_name: str = "base",
        dataset_name: str = "raw",
        entry_delay_bars: int = 0,
    ) -> tuple[list[ReplayTrade], dict[str, int]]:
        trades: list[ReplayTrade] = []
        skips: dict[str, int] = {}

        for sig in signals:
            bars = bars_by_ticker.get(sig.ticker)
            if bars is None:
                skips["skipped_no_data"] = skips.get("skipped_no_data", 0) + 1
                continue

            trade, status = self.simulate_single_signal(
                signal=sig,
                bars=bars,
                cost_model_name=cost_model_name,
                dataset_name=dataset_name,
                entry_delay_bars=entry_delay_bars,
            )
            if trade is not None:
                trades.append(trade)
            else:
                skips[status] = skips.get(status, 0) + 1

        return trades, skips


# ----------------------------------------------------------------------
# Analytics & Guard Layer
# ----------------------------------------------------------------------


def calculate_cell_metrics(trades: Sequence[ReplayTrade], n_signals: int = 0) -> dict[str, Any]:
    n_tr = len(trades)
    if n_tr == 0:
        return {
            "n_signals": n_signals,
            "n_traded": 0,
            "win_rate": 0.0,
            "avg_r_gross": 0.0,
            "avg_r_net": 0.0,
            "avg_gross_pnl_pct": 0.0,
            "avg_net_pnl_pct": 0.0,
            "avg_mfe_r": 0.0,
            "avg_mae_r": 0.0,
            "avg_rr_setup": 0.0,
            "tp_rate": 0.0,
            "outcomes": {"TP": 0, "SL": 0, "TIMEOUT": 0},
            "low_n": True,
            "recommendation_allowed": False,
        }

    winning = [t for t in trades if t.net_pnl_pct > 0]
    win_rate = len(winning) / n_tr
    avg_r_gross = float(np.mean([t.r_multiple_gross for t in trades]))
    avg_r_net = float(np.mean([t.r_multiple_net for t in trades]))
    avg_gross_pnl = float(np.mean([t.gross_pnl_pct for t in trades]))
    avg_net_pnl = float(np.mean([t.net_pnl_pct for t in trades]))
    avg_mfe_r = float(np.mean([t.mfe_r for t in trades]))
    avg_mae_r = float(np.mean([t.mae_r for t in trades]))
    avg_rr_setup = float(np.mean([t.rr_setup for t in trades]))

    outcomes = {"TP": 0, "SL": 0, "TIMEOUT": 0}
    for t in trades:
        outcomes[t.exit_reason] = outcomes.get(t.exit_reason, 0) + 1

    tp_rate = outcomes["TP"] / n_tr
    low_n = n_tr < 10

    return {
        "n_signals": n_signals,
        "n_traded": n_tr,
        "win_rate": win_rate,
        "avg_r_gross": avg_r_gross,
        "avg_r_net": avg_r_net,
        "avg_gross_pnl_pct": avg_gross_pnl,
        "avg_net_pnl_pct": avg_net_pnl,
        "avg_mfe_r": avg_mfe_r,
        "avg_mae_r": avg_mae_r,
        "avg_rr_setup": avg_rr_setup,
        "tp_rate": tp_rate,
        "outcomes": outcomes,
        "low_n": low_n,
        "recommendation_allowed": not low_n,
    }


def analyze_score_buckets(
    trades: Sequence[ReplayTrade],
    all_signals: Sequence[ReplaySignal],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for b_label, low, high in SCORE_BUCKET_DEFS:
        # Long signals
        long_sigs = [
            s
            for s in all_signals
            if s.direction == "long" and s.score is not None and low <= s.score < high
        ]
        long_tr = [
            t
            for t in trades
            if t.direction == "long" and t.signal_score is not None and low <= t.signal_score < high
        ]
        results[f"long_{b_label}"] = calculate_cell_metrics(long_tr, len(long_sigs))

        # Short signals: symmetric via abs(score)
        short_sigs = [
            s
            for s in all_signals
            if s.direction == "short" and s.score is not None and low <= abs(s.score) < high
        ]
        short_tr = [
            t
            for t in trades
            if t.direction == "short"
            and t.signal_score is not None
            and low <= abs(t.signal_score) < high
        ]
        results[f"short_{b_label}"] = calculate_cell_metrics(short_tr, len(short_sigs))

    return results


def analyze_confidence_buckets(
    trades: Sequence[ReplayTrade],
    all_signals: Sequence[ReplaySignal],
) -> dict[str, dict[str, Any]]:
    """Confidence buckets by the stored string key (confidence.low/medium/high)."""
    results: dict[str, dict[str, Any]] = {}
    for key in CONFIDENCE_KEYS:
        sigs = [s for s in all_signals if s.confidence == key]
        tr = [t for t in trades if t.confidence == key]
        results[key] = calculate_cell_metrics(tr, len(sigs))
    results["no_conf"] = calculate_cell_metrics(
        [t for t in trades if t.confidence not in CONFIDENCE_KEYS],
        len([s for s in all_signals if s.confidence not in CONFIDENCE_KEYS]),
    )
    return results


# ----------------------------------------------------------------------
# No-Lookahead Filter Replays (EMA200, RSI extremes)
# ----------------------------------------------------------------------


def _compute_ema(series: pd.Series, span: int = 200) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def evaluate_indicator_filters(
    signals: Sequence[ReplaySignal],
    bars_by_ticker: dict[str, pd.DataFrame],
    engine: SignalReplayEngine,
    cost_model_name: str = "base",
    dataset_name: str = "raw",
) -> dict[str, Any]:
    """Evaluates EMA200 and RSI filters with strict no-lookahead (up to decision bar)."""
    # Precalculate indicators on full series
    augmented_bars: dict[str, pd.DataFrame] = {}
    for ticker, df in bars_by_ticker.items():
        if df is None or len(df) == 0:
            continue
        c_df = df.copy()
        c_df["ema200"] = _compute_ema(c_df["close"], span=200)
        c_df["rsi14"] = _compute_rsi(c_df["close"], period=14)
        augmented_bars[ticker] = c_df

    baseline_trades, _ = engine.replay_dataset(
        signals, augmented_bars, cost_model_name=cost_model_name, dataset_name=dataset_name
    )
    baseline_metrics = calculate_cell_metrics(baseline_trades, len(signals))

    # Evaluate EMA200 filter for Longs: Decision bar close >= EMA200 (if close < EMA200 -> filtered out)
    filtered_ema_trades: list[ReplayTrade] = []
    dropped_ema_count = 0

    filtered_rsi_trades: list[ReplayTrade] = []
    dropped_rsi_count = 0

    for sig in signals:
        bars = augmented_bars.get(sig.ticker)
        if bars is None:
            continue
        sig_date = sig.signal_date
        bar_dates = list(bars["date"])
        # Decision bar = last bar <= sig_date
        past_indices = [i for i, d in enumerate(bar_dates) if d <= sig_date]
        if not past_indices:
            # no indicator info -> keep
            trade, _ = engine.simulate_single_signal(sig, bars, cost_model_name, dataset_name)
            if trade:
                filtered_ema_trades.append(trade)
                filtered_rsi_trades.append(trade)
            continue

        dec_idx = past_indices[-1]
        dec_bar = bars.iloc[dec_idx]
        dec_close = float(dec_bar["close"])
        dec_ema = float(dec_bar["ema200"])
        dec_rsi = float(dec_bar["rsi14"])

        trade, _ = engine.simulate_single_signal(sig, bars, cost_model_name, dataset_name)
        if not trade:
            continue

        # EMA rule: Longs must have dec_close >= dec_ema
        if sig.direction == "long" and dec_close < dec_ema:
            dropped_ema_count += 1
        else:
            filtered_ema_trades.append(trade)

        # RSI rule: Longs veto if RSI > 70 (overbought), Shorts veto if RSI < 30 (oversold)
        if (sig.direction == "long" and dec_rsi > 70.0) or (
            sig.direction == "short" and dec_rsi < 30.0
        ):
            dropped_rsi_count += 1
        else:
            filtered_rsi_trades.append(trade)

    ema_metrics = calculate_cell_metrics(filtered_ema_trades, len(signals) - dropped_ema_count)
    rsi_metrics = calculate_cell_metrics(filtered_rsi_trades, len(signals) - dropped_rsi_count)

    return {
        "baseline": baseline_metrics,
        "ema200_filter": {
            "metrics": ema_metrics,
            "dropped_count": dropped_ema_count,
            "delta_avg_r_net": ema_metrics["avg_r_net"] - baseline_metrics["avg_r_net"],
            "delta_win_rate": ema_metrics["win_rate"] - baseline_metrics["win_rate"],
        },
        "rsi_extreme_filter": {
            "metrics": rsi_metrics,
            "dropped_count": dropped_rsi_count,
            "delta_avg_r_net": rsi_metrics["avg_r_net"] - baseline_metrics["avg_r_net"],
            "delta_win_rate": rsi_metrics["win_rate"] - baseline_metrics["win_rate"],
        },
    }


def evaluate_entry_delays(
    signals: Sequence[ReplaySignal],
    bars_by_ticker: dict[str, pd.DataFrame],
    engine: SignalReplayEngine,
    cost_model_name: str = "base",
    dataset_name: str = "raw",
    delays: Sequence[int] = (0, 1, 2, 3),
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for d in delays:
        tr, _ = engine.replay_dataset(
            signals,
            bars_by_ticker,
            cost_model_name=cost_model_name,
            dataset_name=dataset_name,
            entry_delay_bars=d,
        )
        results[f"delay_+{d}"] = calculate_cell_metrics(tr, len(signals))
    return results


def evaluate_hysteresis(
    signals: Sequence[ReplaySignal],
    bars_by_ticker: dict[str, pd.DataFrame],
    engine: SignalReplayEngine,
    cost_model_name: str = "base",
    max_gap_bars: int = 5,
    params: StrategyParams | None = None,
) -> dict[str, Any]:
    """Hysteresis: requires >=2 actionable signals in episode; enters on next bar of 2nd signal."""
    p = params or StrategyParams()
    raw_sigs = build_dataset_raw(signals)
    by_ticker: dict[str, list[ReplaySignal]] = {}
    for s in raw_sigs:
        if s.is_radar:
            continue
        by_ticker.setdefault(s.ticker, []).append(s)

    selected_2nd_sigs: list[ReplaySignal] = []
    total_episodes = 0
    unconfirmed_episodes = 0

    for ticker, sig_list in by_ticker.items():
        sig_list.sort(key=lambda s: s.timestamp)
        bars = bars_by_ticker.get(ticker)
        bar_dates = list(bars["date"]) if bars is not None and "date" in bars.columns else []

        episodes: list[list[ReplaySignal]] = []
        current_ep: list[ReplaySignal] = []

        for sig in sig_list:
            if not current_ep:
                current_ep.append(sig)
            else:
                last_sig = current_ep[-1]
                if last_sig.direction != sig.direction:
                    episodes.append(current_ep)
                    current_ep = [sig]
                else:
                    is_gap_exceeded = False
                    if bar_dates:
                        try:
                            i1 = next(
                                i for i, d in enumerate(bar_dates) if d >= last_sig.signal_date
                            )
                            i2 = next(i for i, d in enumerate(bar_dates) if d >= sig.signal_date)
                            if (i2 - i1) > max_gap_bars:
                                is_gap_exceeded = True
                        except StopIteration:
                            pass
                    if is_gap_exceeded:
                        episodes.append(current_ep)
                        current_ep = [sig]
                    else:
                        current_ep.append(sig)
        if current_ep:
            episodes.append(current_ep)

        for ep in episodes:
            total_episodes += 1
            actionable_in_ep = [s for s in ep if s.is_actionable(p)]
            if len(actionable_in_ep) >= 2:
                selected_2nd_sigs.append(actionable_in_ep[1])
            else:
                unconfirmed_episodes += 1

    trades, _ = engine.replay_dataset(
        selected_2nd_sigs,
        bars_by_ticker,
        cost_model_name=cost_model_name,
        dataset_name="hysteresis",
    )
    metrics = calculate_cell_metrics(trades, len(selected_2nd_sigs))
    return {
        "metrics": metrics,
        "total_episodes": total_episodes,
        "confirmed_episodes": len(selected_2nd_sigs),
        "unconfirmed_episodes": unconfirmed_episodes,
    }


def generate_decision_report(
    score_buckets: dict[str, dict[str, Any]],
    guard_threshold: int = 10,
) -> dict[str, Any]:
    eligible_long_cells: list[str] = []
    eligible_short_cells: list[str] = []

    for k, v in score_buckets.items():
        if not v.get("low_n", True):
            if k.startswith("long_"):
                eligible_long_cells.append(k)
            elif k.startswith("short_"):
                eligible_short_cells.append(k)

    # Sort all cells by N desc to highlight highest N sample points
    all_cells_sorted = sorted(
        score_buckets.items(), key=lambda item: item[1]["n_traded"], reverse=True
    )
    top_3_by_n = [
        {
            "cell": c[0],
            "n_traded": c[1]["n_traded"],
            "avg_r_net": c[1]["avg_r_net"],
            "win_rate": c[1]["win_rate"],
        }
        for c in all_cells_sorted[:3]
    ]

    proposals_ready = len(eligible_long_cells) > 0
    short_note = (
        f"{len(eligible_short_cells)} short cell(s) passed guard N>={guard_threshold}. "
        "Treated as hypothetical execution report."
        if eligible_short_cells
        else "No short cells passed guard."
    )

    decision_status = (
        "proposals_ready" if proposals_ready else "no_threshold_change_evidence_accumulation"
    )

    return {
        "decision_status": decision_status,
        "proposals_ready": proposals_ready,
        "eligible_long_cells": eligible_long_cells,
        "eligible_short_cells": eligible_short_cells,
        "short_execution_note": short_note,
        "top_sample_cells": top_3_by_n,
    }
