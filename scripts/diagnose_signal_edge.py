"""Deney E — Signal-edge diagnosis (Phases 0 and 1).

Cache-only, read-only diagnosis of why per-signal net WR sits at ~50%.

Phase 0 (measurement audit):
  - regenerates the pinned 508-signal reference set from cache through the
    canonical ``Backtester._precalculate_signals`` path and asserts it
    matches ``results/prediction_signals_macro_observe.csv`` exactly
    (parity anchor — the run aborts on any mismatch)
  - forward returns at horizons {1,3,5,10,20} on TWO bases:
      (i)  signal-day close -> t+h close   (information content)
      (ii) t+1 open        -> t+h close   (tradeable; WR target basis)
  - matched baseline: for each signal, all non-signal days of the same
    ticker within ±30 trading days (deterministic; INCOMPLETE excluded)
  - paired edge per signal (signal return − mean matched-baseline return),
    gross AND net (evaluator cost model), with date-block bootstrap CIs
    (blocks resample whole cross-sections; lengths {10,20,40}, 1000 draws)
  - vol-normalized edge (return / prior 14-day ATR)
  - censoring report, design effect / effective n, n required for WR 60%
  - per-year breakdown

Phase 1 (component IC analysis):
  - every ticker × every day: raw component scores
    (score_momentum/trend/volume/structure) + atomic indicator features,
    plus per-ticker ``detect_regime`` classification
  - Spearman IC per feature × horizon × basis × condition
    {unconditional, BULL, BEAR, SIDEWAYS, signal-day}
  - BH FDR 5% per (basis × condition) family; n<30 cells flagged "indicative"
  - per-year IC sign stability

Usage:
    uv run python scripts/diagnose_signal_edge.py --phase 0
    uv run python scripts/diagnose_signal_edge.py --phase 1
    uv run python scripts/diagnose_signal_edge.py --phase all
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_walk_forward_bist30 import (  # noqa: E402
    BIST30_TICKERS,
    DEFAULT_CACHE_DIR,
    _cache_path,
    _load_csv_fallback,
    _normalize_ohlcv,
)

from bist_bot.backtest.engine import Backtester  # noqa: E402
from bist_bot.backtest.models import CostModel  # noqa: E402
from bist_bot.config import settings  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.regime import detect_regime  # noqa: E402
from bist_bot.strategy.scoring import (  # noqa: E402
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)

HORIZONS = (1, 3, 5, 10, 20)
BLOCK_LENGTHS = (10, 20, 40)
N_BOOTSTRAP = 1000
BOOTSTRAP_SEED = 20260828
MATCH_WINDOW = 30
FDR_Q = 0.05
MIN_CELL_N = 30
IC_MATERIAL = 0.02

REFERENCE_CSV = REPO_ROOT / "results" / "prediction_signals_macro_observe.csv"

ATOMIC_FEATURES = [
    "rsi",
    "stoch_k",
    "stoch_d",
    "cci",
    "adx",
    "plus_di",
    "minus_di",
    "ema_slope",
    "sma_cross_bull",
    "sma_cross_bear",
    "macd_cross_bull",
    "macd_cross_bear",
    "bb_below_lower",
    "bb_above_upper",
    "obv_up",
    "obv_down",
    "pv_bull",
    "pv_bear",
    "dist_to_support_pct",
    "dist_to_resistance_pct",
]
COMPONENT_FEATURES = [
    "score_momentum",
    "score_trend",
    "score_volume",
    "score_structure",
    "score_total",
]


# ---------------------------------------------------------------------------
# Data access (cache-only)
# ---------------------------------------------------------------------------


def _load_cached(ticker: str, cache_dir: Path, period: str = "3y") -> pd.DataFrame | None:
    path = _cache_path(cache_dir, ticker, period)
    if path.exists():
        try:
            return _normalize_ohlcv(pd.read_parquet(path))
        except Exception:
            pass
    return _load_csv_fallback(cache_dir, ticker, period)


def enriched_frame(df: pd.DataFrame, backtester: Backtester) -> pd.DataFrame:
    """Same preparation the per-signal evaluator applies."""
    enriched = backtester.indicators.add_all(df)
    return enriched.dropna(subset=["rsi", f"sma_{settings.SMA_SLOW}"])


def precalculated_signals(enriched: pd.DataFrame, backtester: Backtester) -> pd.DataFrame:
    sig = backtester._precalculate_signals(enriched)
    if getattr(sig.index, "tz", None) is not None:
        sig = sig.tz_localize(None)
    return sig


def extract_signal_rows(sig: pd.DataFrame, ticker: str) -> list[dict[str, object]]:
    """Signal rows exactly as the per-signal evaluator enumerates them.

    A post-shift ``enter_signal`` at bar ``i`` is decided at the close of
    bar ``i-1`` (signal_date) and executed at the open of bar ``i``
    (entry_date). Censoring: entry bars without 5 more closes ahead are
    INCOMPLETE (mirrors the evaluator's forward-data rule).
    """
    dates = sig.index
    enters = sig["enter_signal"].to_numpy(dtype=bool)
    scores = sig["score"].to_numpy(dtype=float)
    n = len(sig)
    rows: list[dict[str, object]] = []
    for i in range(1, n):
        if not enters[i]:
            continue
        # Mirrors the evaluator: complete iff the 5-bar hold (entry bar + 4
        # follow-ups) fits into available data (i + max_hold - 1 <= n - 1).
        complete = i + 4 <= n - 1
        rows.append(
            {
                "ticker": ticker,
                "signal_date": dates[i - 1],
                "entry_date": dates[i],
                "pos": i,  # entry position within this ticker's frame
                "score": float(scores[i]),
                "complete": bool(complete),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Forward returns
# ---------------------------------------------------------------------------


def forward_return(
    closes: np.ndarray, opens: np.ndarray, pos: int, horizon: int, basis: str
) -> float | None:
    """Forward return for a signal at *frame position* ``pos`` (entry bar).

    pos is the entry-bar index i (execution bar). basis "i": close[pos-1]
    (signal-day close) -> close[pos-1+h]; basis "ii": open[pos] (t+1 open)
    -> close[pos-1+h]. Returns None when the window is censored.
    """
    end = pos - 1 + horizon
    if end >= len(closes) or pos < 1:
        return None
    base = closes[pos - 1] if basis == "i" else opens[pos]
    if base <= 0:
        return None
    return float(closes[end] / base - 1.0)


# ---------------------------------------------------------------------------
# Reference set + parity
# ---------------------------------------------------------------------------


def build_signal_universe(
    cache_dir: Path, backtester: Backtester
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Regenerate the signal set and keep enriched/signal frames per ticker."""
    frames: dict[str, pd.DataFrame] = {}
    sig_frames: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for ticker in BIST30_TICKERS:
        df = _load_cached(ticker, cache_dir)
        if df is None or len(df) < 60:
            continue
        if getattr(df.index, "tz", None) is not None:
            df = df.tz_localize(None)
        enriched = enriched_frame(df, backtester)
        if len(enriched) < 3:
            continue
        sig = precalculated_signals(enriched, backtester)
        frames[ticker] = enriched
        sig_frames[ticker] = sig
        rows.extend(extract_signal_rows(sig, ticker))
    signals = pd.DataFrame(rows)
    return signals, frames, sig_frames


def load_reference_keys(path: Path) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            keys.add((row["ticker"], row["signal_date"], row["entry_date"]))
    return keys


def assert_parity(signals: pd.DataFrame, reference_csv: Path) -> None:
    ref = load_reference_keys(reference_csv)
    got = {
        (
            str(r["ticker"]),
            str(pd.Timestamp(r["signal_date"]).date()),
            str(pd.Timestamp(r["entry_date"]).date()),
        )
        for _, r in signals.iterrows()
    }
    if got != ref:
        missing = sorted(ref - got)[:5]
        extra = sorted(got - ref)[:5]
        raise AssertionError(
            "signal-set parity FAILED: "
            f"{len(ref - got)} missing / {len(got - ref)} extra. "
            f"missing[:5]={missing} extra[:5]={extra}"
        )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def block_bootstrap_ci(
    diffs: np.ndarray,
    dates: np.ndarray,
    *,
    block: int,
    n_boot: int,
    seed: int,
) -> tuple[float, float, float]:
    """Date-block bootstrap CI for the mean of per-signal paired diffs.

    Blocks are consecutive unique dates; whole cross-sections (all tickers of
    a date) are resampled together, preserving cross-sectional and forward-
    window overlap correlation.
    """
    if len(diffs) == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    unique_dates = np.unique(dates)
    n_dates = len(unique_dates)
    if n_dates < 2 * block:
        # Not enough dates for blocking: fall back to iid bootstrap.
        idx = rng.integers(0, len(diffs), size=(n_boot, len(diffs)))
        means = diffs[idx].mean(axis=1)
    else:
        n_blocks = math.ceil(n_dates / block)
        date_to_idx: dict[object, list[int]] = {}
        for i, d in enumerate(dates):
            date_to_idx.setdefault(d, []).append(i)
        means = np.empty(n_boot)
        for b in range(n_boot):
            chosen = rng.integers(0, n_blocks, size=n_blocks)
            idxs: list[int] = []
            for blk in chosen:
                start = blk * block
                for d in unique_dates[start : start + block]:
                    idxs.extend(date_to_idx[d])
            means[b] = diffs[np.asarray(idxs, dtype=int)].mean() if idxs else float("nan")
        means = means[~np.isnan(means)]
    if len(means) == 0:
        return (float("nan"), float("nan"), float("nan"))
    return (
        float(np.mean(diffs)),
        float(np.percentile(means, 2.5)),
        float(np.percentile(means, 97.5)),
    )


def design_effect(dates: np.ndarray, values: np.ndarray) -> tuple[float, float]:
    """Approximate design effect 1+(m-1)*rho from date clustering."""
    df = pd.DataFrame({"d": dates, "v": values})
    groups = df.groupby("d")["v"]
    m = float(groups.size().mean())
    grand = df["v"].mean()
    between = float((groups.mean() - grand).pow(2).mean())
    total = float(df["v"].var(ddof=1)) if len(df) > 1 else 0.0
    if total <= 0 or m <= 1:
        return 1.0, m
    within = max(total - between, 1e-12)
    rho = max(between - within / max(len(groups), 1), 0.0) / total
    deff = 1.0 + (m - 1.0) * rho
    return max(deff, 1.0), m


def n_required_wr60(deff: float) -> int:
    """Independent-observation equivalent needed to detect 50% -> 60% WR."""
    z_alpha, z_beta = 1.959964, 0.841621
    p0, p1 = 0.5, 0.6
    n = ((z_alpha + z_beta) ** 2) * (p0 * (1 - p0) + p1 * (1 - p1)) / (p1 - p0) ** 2
    return math.ceil(n * max(deff, 1.0))


def spearman_ic(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Spearman rho and normal-approx p-value (Fisher z)."""
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 3 or np.std(x) == 0 or np.std(y) == 0:
        return (float("nan"), float("nan"))
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    if abs(rho) >= 1.0:
        return (rho, 0.0)
    z = math.atanh(rho) * math.sqrt(n - 3)
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return (rho, p)


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def bh_fdr(pvals: list[float], q: float = FDR_Q) -> list[bool]:
    """Benjamini-Hochberg rejection mask."""
    n = len(pvals)
    order = sorted(range(n), key=lambda i: (math.inf if math.isnan(pvals[i]) else pvals[i]))
    keep = [False] * n
    for rank, idx in enumerate(order, start=1):
        p = pvals[idx]
        if not math.isnan(p) and p <= (rank / n) * q:
            keep[idx] = True
        else:
            break
    return keep


# ---------------------------------------------------------------------------
# Cost model (mirrors evaluate_july_2026_predictions.py)
# ---------------------------------------------------------------------------


def net_of_cost(gross: float, cost: CostModel) -> float:
    """Approximate per-signal net return from gross return (one round trip).

    Uses the evaluator's single-pass model: price impact (slippage +
    half-spread) once per side, buy fees, sell fees.
    """
    impact = (cost.fixed_slippage_bps + cost.spread_bps) / 10_000
    buy_fee = (cost.commission_bps + cost.exchange_fee_bps) / 10_000
    sell_fee = (
        cost.commission_bps + cost.exchange_fee_bps + cost.stamp_tax_bps + cost.bsmv_bps
    ) / 10_000
    entry = 1.0 * (1 + impact) * (1 + buy_fee)
    exit_ = (1.0 + gross) * (1 - impact) * (1 - sell_fee)
    return exit_ / entry - 1.0


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_reproducibility(cache_dir: Path, out_path: Path, args: argparse.Namespace) -> None:
    lines = [
        f"git SHA: {_git_sha()}",
        f"argv: {' '.join(sys.argv)}",
        f"phase: {args.phase}",
        "cache SHA256:",
    ]
    for ticker in BIST30_TICKERS:
        path = _cache_path(cache_dir, ticker, "3y")
        if path.exists():
            lines.append(f"  {_hash_file(path)[:16]}  {path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 0
# ---------------------------------------------------------------------------


@dataclass
class Phase0Result:
    rows: list[dict[str, object]]
    summary: list[dict[str, object]]


def run_phase0(
    signals: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    cost: CostModel,
) -> Phase0Result:
    atr: dict[str, np.ndarray] = {
        t: f["atr"].to_numpy(dtype=float) if "atr" in f.columns else np.full(len(f), np.nan)
        for t, f in frames.items()
    }
    closes = {t: f["close"].to_numpy(dtype=float) for t, f in frames.items()}
    opens = {t: f["open"].to_numpy(dtype=float) for t, f in frames.items()}

    rows: list[dict[str, object]] = []
    for _, r in signals.iterrows():
        ticker = str(r["ticker"])
        pos = int(r["pos"])
        c, o = closes[ticker], opens[ticker]
        base_ii = forward_return(c, o, pos, 5, "ii")
        base_i = forward_return(c, o, pos, 5, "i")
        atr14 = atr[ticker][pos - 1] if pos - 1 < len(atr[ticker]) else float("nan")
        rows.append(
            {
                "ticker": ticker,
                "signal_date": pd.Timestamp(r["signal_date"]).date().isoformat(),
                "entry_date": pd.Timestamp(r["entry_date"]).date().isoformat(),
                "score": r["score"],
                "complete": r["complete"],
                "fwd5_close_close": base_i,
                "fwd5_open_close": base_ii,
                "net5_open_close": (net_of_cost(base_ii, cost) if base_ii is not None else None),
                "atr14_prior": atr14,
                "volnorm_edge": (
                    (base_ii - 0.0) / atr14
                    if base_ii is not None and atr14 == atr14 and atr14 > 0
                    else None
                ),
            }
        )
    detail = pd.DataFrame(rows)

    # ---- matched baseline (basis ii, h=5) -----------------------------------
    baseline: dict[tuple[str, str], list[float]] = {}
    signal_pos = {t: set(signals.loc[signals["ticker"] == t, "pos"].astype(int)) for t in frames}
    for _, r in signals.iterrows():
        ticker = str(r["ticker"])
        pos = int(r["pos"])
        c, o = closes[ticker], opens[ticker]
        n = len(c)
        vals: list[float] = []
        for j in range(max(1, pos - MATCH_WINDOW), min(n, pos + MATCH_WINDOW + 1)):
            if j == pos or j in signal_pos[ticker]:
                continue
            v = forward_return(c, o, j, 5, "ii")
            if v is not None:
                vals.append(v)
        baseline[(ticker, str(pd.Timestamp(r["signal_date"]).date()))] = vals

    diffs: list[float] = []
    diff_dates: list[pd.Timestamp] = []
    for _, r in detail.iterrows():
        if not r["complete"] or r["fwd5_open_close"] is None:
            continue
        key = (r["ticker"], r["signal_date"])
        vals = baseline.get(key, [])
        if not vals:
            continue
        diffs.append(float(r["fwd5_open_close"]) - float(np.mean(vals)))
        diff_dates.append(pd.Timestamp(r["signal_date"]))

    diffs_arr = np.asarray(diffs)
    dates_arr = np.asarray(diff_dates)
    deff, m = design_effect(dates_arr, diffs_arr)
    eff_n = len(diffs_arr) / deff if deff > 0 else float("nan")

    complete = detail[detail["complete"]].copy()
    sig_ret = complete["fwd5_open_close"].dropna().to_numpy()
    all_baseline = np.concatenate([v for v in baseline.values() if v]) if baseline else np.array([])
    gap_component = (
        complete["fwd5_close_close"].dropna().mean() - complete["fwd5_open_close"].dropna().mean()
    )

    summary: list[dict[str, object]] = [
        {"metric": "n_signals", "value": len(detail)},
        {"metric": "n_complete", "value": len(complete)},
        {"metric": "n_incomplete", "value": int((~detail["complete"]).sum())},
        {
            "metric": "signal_fwd5_open_close_mean",
            "value": float(np.mean(sig_ret)) if len(sig_ret) else None,
        },
        {
            "metric": "signal_fwd5_open_close_uprate",
            "value": float((sig_ret > 0).mean()) if len(sig_ret) else None,
        },
        {
            "metric": "baseline_fwd5_open_close_mean",
            "value": float(np.mean(all_baseline)) if len(all_baseline) else None,
        },
        {
            "metric": "baseline_fwd5_open_close_uprate",
            "value": float((all_baseline > 0).mean()) if len(all_baseline) else None,
        },
        {
            "metric": "paired_edge_mean",
            "value": float(diffs_arr.mean()) if len(diffs_arr) else None,
        },
        {"metric": "design_effect", "value": deff},
        {"metric": "avg_signals_per_date", "value": m},
        {"metric": "effective_n", "value": eff_n},
        {"metric": "n_required_wr60", "value": n_required_wr60(deff)},
        {"metric": "overnight_gap_component_mean", "value": float(gap_component)},
    ]
    for b in BLOCK_LENGTHS:
        mean_, lo, hi = block_bootstrap_ci(
            diffs_arr, dates_arr, block=b, n_boot=N_BOOTSTRAP, seed=BOOTSTRAP_SEED
        )
        summary.append(
            {
                "metric": f"paired_edge_bootstrap_b{b}",
                "value": f"mean={mean_:+.5f} CI95=[{lo:+.5f}, {hi:+.5f}]",
            }
        )

    # per-year breakdown
    complete = complete.assign(year=pd.to_datetime(complete["signal_date"]).dt.year)
    for year, grp in complete.groupby("year"):
        vals = grp["fwd5_open_close"].dropna().to_numpy()
        summary.append(
            {
                "metric": f"year_{year}",
                "value": (
                    f"n={len(vals)} up={float((vals > 0).mean()):.3f} "
                    f"mean={float(np.mean(vals)):+.4f}"
                ),
            }
        )

    return Phase0Result(rows=rows, summary=summary)


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------


def _atomic_features(last: pd.Series, slope: float | None) -> dict[str, float]:
    def _f(name: str) -> float:
        v = last.get(name)
        return float(v) if v is not None and pd.notna(v) else float("nan")

    return {
        "rsi": _f("rsi"),
        "stoch_k": _f("stoch_k"),
        "stoch_d": _f("stoch_d"),
        "cci": _f("cci"),
        "adx": _f("adx"),
        "plus_di": _f("plus_di"),
        "minus_di": _f("minus_di"),
        "ema_slope": float(slope) if slope is not None else float("nan"),
        "sma_cross_bull": 1.0 if last.get("sma_cross") == "GOLDEN_CROSS" else 0.0,
        "sma_cross_bear": 1.0 if last.get("sma_cross") == "DEATH_CROSS" else 0.0,
        "macd_cross_bull": 1.0 if last.get("macd_cross") == "BULLISH" else 0.0,
        "macd_cross_bear": 1.0 if last.get("macd_cross") == "BEARISH" else 0.0,
        "bb_below_lower": 1.0 if last.get("bb_position") == "BELOW_LOWER" else 0.0,
        "bb_above_upper": 1.0 if last.get("bb_position") == "ABOVE_UPPER" else 0.0,
        "obv_up": 1.0 if last.get("obv_trend") == "UP" else 0.0,
        "obv_down": 1.0 if last.get("obv_trend") == "DOWN" else 0.0,
        "pv_bull": 1.0 if last.get("price_volume_direction") == "BULLISH_CONFIRMATION" else 0.0,
        "pv_bear": 1.0 if last.get("price_volume_direction") == "BEARISH_CONFIRMATION" else 0.0,
        "dist_to_support_pct": _f("dist_to_support_pct"),
        "dist_to_resistance_pct": _f("dist_to_resistance_pct"),
    }


def compute_row_features(params: StrategyParams, df: pd.DataFrame, j: int) -> dict[str, float]:
    """Component scores + atomic features at frame position ``j``.

    ``j`` is the decision bar (last row of the visible slice). Component
    scores call the exact production scorers with the same call signature
    the engine uses.
    """
    hist = df.iloc[: j + 1]
    last, prev = df.iloc[j], df.iloc[j - 1]
    s1, _ = score_momentum(params, last, prev)
    s2, _ = score_trend(params, last, prev, hist)
    s3, _ = score_volume(params, last, prev)
    s4, _ = score_structure(params, last)
    slope = None
    ema_col = f"ema_{settings.EMA_LONG}"
    lb = int(getattr(params, "slope_lookback", 40))
    if ema_col in hist.columns and len(hist) > lb:
        slope = float(hist[ema_col].iloc[-1] - hist[ema_col].iloc[-1 - lb])
    feats = _atomic_features(last, slope)
    feats.update(
        {
            "score_momentum": float(s1),
            "score_trend": float(s2),
            "score_volume": float(s3),
            "score_structure": float(s4),
            "score_total": float(s1 + s2 + s3 + s4),
        }
    )
    return feats


def build_feature_panel(
    frames: dict[str, pd.DataFrame],
    signals: pd.DataFrame,
    params: StrategyParams,
    *,
    max_horizon: int = max(HORIZONS),
) -> pd.DataFrame:
    signal_pos = {
        t: set(signals.loc[signals["ticker"] == t, "pos"].astype(int) - 1) for t in frames
    }
    rows: list[dict[str, object]] = []
    for ticker, df in frames.items():
        closes = df["close"].to_numpy(dtype=float)
        opens = df["open"].to_numpy(dtype=float)
        n = len(df)
        for j in range(1, n - 1):
            feats = compute_row_features(params, df, j)
            regime = detect_regime(df.iloc[: j + 1])
            row: dict[str, object] = {
                "ticker": ticker,
                "date": df.index[j],
                "regime": regime.value,
                "is_signal_day": 1 if j in signal_pos.get(ticker, set()) else 0,
            }
            row.update(feats)
            for h in HORIZONS:
                row[f"fwd{h}_i"] = forward_return(closes, opens, j + 1, h, "i")
                row[f"fwd{h}_ii"] = forward_return(closes, opens, j + 1, h, "ii")
            rows.append(row)
    return pd.DataFrame(rows)


def run_phase1(panel: pd.DataFrame) -> pd.DataFrame:
    conditions = ["unconditional", "BULL", "BEAR", "SIDEWAYS", "signal_day"]
    features = COMPONENT_FEATURES + ATOMIC_FEATURES
    records: list[dict[str, object]] = []
    for basis in ("i", "ii"):
        for cond in conditions:
            if cond == "unconditional":
                sub = panel
            elif cond == "signal_day":
                sub = panel[panel["is_signal_day"] == 1]
            else:
                sub = panel[panel["regime"] == cond]
            group_records: list[int] = []
            for feat in features:
                for h in HORIZONS:
                    col = f"fwd{h}_{basis}"
                    x = sub[feat].to_numpy(dtype=float)
                    y = sub[col].to_numpy(dtype=float)
                    mask = ~(np.isnan(x) | np.isnan(y))
                    n = int(mask.sum())
                    rho, p = spearman_ic(x, y)
                    idx = len(records)
                    group_records.append(idx)
                    records.append(
                        {
                            "basis": basis,
                            "condition": cond,
                            "feature": feat,
                            "horizon": h,
                            "n": n,
                            "ic": rho,
                            "p_value": p,
                            "material": bool(abs(rho) >= IC_MATERIAL) if rho == rho else False,
                            "indicative": n < MIN_CELL_N,
                        }
                    )
            keep = bh_fdr([records[i]["p_value"] for i in group_records])
            for k, idx in zip(group_records, keep, strict=True):
                records[idx]["fdr_significant"] = bool(k)
    out = pd.DataFrame(records)

    # per-year sign stability (basis ii, h=5)
    panel5 = panel.dropna(subset=["fwd5_ii"]).copy()
    panel5["year"] = pd.to_datetime(panel5["date"]).dt.year
    for feat in features:
        signs: dict[int, float] = {}
        for year, grp in panel5.groupby("year"):
            if len(grp) >= MIN_CELL_N:
                rho, _ = spearman_ic(
                    grp[feat].to_numpy(dtype=float), grp["fwd5_ii"].to_numpy(dtype=float)
                )
                if rho == rho:
                    signs[int(year)] = rho
        if signs:
            consistent = len({np.sign(v) for v in signs.values()}) == 1
            out.loc[out["feature"] == feat, "year_sign_consistent"] = consistent
            out.loc[out["feature"] == feat, "year_signs"] = str(
                {y: round(v, 3) for y, v in sorted(signs.items())}
            )
    return out


# ---------------------------------------------------------------------------
# Phase 2 — gate & threshold marginal effects
# ---------------------------------------------------------------------------

GATE_VARIANTS: dict[str, dict[str, object]] = {
    "baseline": {},
    "sideways_x1.0": {"sideways_score_multiplier": 1.0},
    "no_momentum_confirmation": {"momentum_confirmation_threshold": 0.0},
    "no_obv_divergence": {"obv_divergence_block_enabled": False},
    "ctm_1.0": {"counter_trend_multiplier": 1.0},
    "chase_on": {"chase_block_enabled": True},
    "agreement_on": {"agreement_gate_enabled": True},
}

THRESHOLD_SWEEP = (15, 20, 25, 30, 35, 40, 45)


def _variant_signals(
    frames: dict[str, pd.DataFrame], params: StrategyParams, overrides: dict[str, object]
) -> pd.DataFrame:
    import copy as _copy

    p = _copy.deepcopy(params)
    for k, v in overrides.items():
        setattr(p, k, v)
    bt = Backtester(strategy_params=p, target_rr=2.0, cost_model=CostModel())
    rows: list[dict[str, object]] = []
    for ticker, enriched in frames.items():
        sig = precalculated_signals(enriched, bt)
        rows.extend(extract_signal_rows(sig, ticker))
    return pd.DataFrame(rows)


def _fwd5_map(frames: dict[str, pd.DataFrame]) -> dict[tuple[str, int], float]:
    out: dict[tuple[str, int], float] = {}
    for ticker, df in frames.items():
        c = df["close"].to_numpy(dtype=float)
        o = df["open"].to_numpy(dtype=float)
        for pos in range(1, len(c)):
            v = forward_return(c, o, pos, 5, "ii")
            if v is not None:
                out[(ticker, pos)] = v
    return out


def run_phase2(
    frames: dict[str, pd.DataFrame],
    sig_frames: dict[str, pd.DataFrame],
    signals: pd.DataFrame,
    params: StrategyParams,
) -> list[dict[str, object]]:
    fwd = _fwd5_map(frames)
    base_keys = {(str(r["ticker"]), int(r["pos"])) for _, r in signals.iterrows()}
    rows: list[dict[str, object]] = []

    def _stats(keys: set[tuple[str, int]]) -> tuple[int, float, float]:
        vals = [fwd[k] for k in keys if k in fwd]
        if not vals:
            return 0, float("nan"), float("nan")
        arr = np.asarray(vals)
        return len(arr), float(arr.mean()), float((arr > 0).mean())

    for name, overrides in GATE_VARIANTS.items():
        variant = _variant_signals(frames, params, overrides)
        vkeys = {(str(r["ticker"]), int(r["pos"])) for _, r in variant.iterrows()}
        kept = vkeys & base_keys
        removed = base_keys - vkeys
        added = vkeys - base_keys
        for label, keys in (
            ("kept", kept),
            ("removed_by_gate", removed),
            ("added_by_gate", added),
        ):
            n, mean_, up = _stats(keys)
            rows.append(
                {
                    "variant": name,
                    "subset": label,
                    "n": n,
                    "mean_fwd5_ii": mean_,
                    "up_rate": up,
                    "indicative": n < MIN_CELL_N,
                }
            )
        rows.append(
            {
                "variant": name,
                "subset": "TOTAL",
                "n": len(vkeys),
                "mean_fwd5_ii": _stats(vkeys)[1],
                "up_rate": _stats(vkeys)[2],
                "indicative": len(vkeys) < MIN_CELL_N,
            }
        )

    # threshold sweep on the baseline precalculated scores
    for thr in THRESHOLD_SWEEP:
        keys: set[tuple[str, int]] = set()
        for ticker, sig in sig_frames.items():
            scores = sig["score"].to_numpy(dtype=float)
            for pos in range(1, len(sig)):
                if scores[pos] >= thr:
                    keys.add((ticker, pos))
        n, mean_, up = _stats(keys)
        rows.append(
            {
                "variant": f"buy_threshold_{thr}",
                "subset": "TOTAL",
                "n": n,
                "mean_fwd5_ii": mean_,
                "up_rate": up,
                "indicative": n < MIN_CELL_N,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Phase 3 — fill timing decomposition
# ---------------------------------------------------------------------------


def run_phase3(frames: dict[str, pd.DataFrame], signals: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, r in signals.iterrows():
        ticker = str(r["ticker"])
        pos = int(r["pos"])
        df = frames[ticker]
        if pos >= len(df):
            continue
        t_close = float(df["close"].iloc[pos - 1])
        e_open = float(df["open"].iloc[pos])
        e_close = float(df["close"].iloc[pos])
        rows.append(
            {
                "ticker": ticker,
                "signal_date": pd.Timestamp(r["signal_date"]).date().isoformat(),
                "entry_date": pd.Timestamp(r["entry_date"]).date().isoformat(),
                "overnight_gap_pct": (e_open / t_close - 1.0) * 100.0,
                "day1_drift_pct": (e_close / e_open - 1.0) * 100.0,
                "rsi": float(df["rsi"].iloc[pos - 1]) if "rsi" in df.columns else float("nan"),
                "bb_above_upper": 1 if df.iloc[pos - 1].get("bb_position") == "ABOVE_UPPER" else 0,
                "golden_cross": 1 if df.iloc[pos - 1].get("sma_cross") == "GOLDEN_CROSS" else 0,
                "macd_bull": 1 if df.iloc[pos - 1].get("macd_cross") == "BULLISH" else 0,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Phase 4 — exit surface
# ---------------------------------------------------------------------------


def simulate_exit(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    exits: np.ndarray,
    atr: np.ndarray,
    entry: int,
    *,
    stop: float,
    rr: float,
    max_hold: int,
    trailing_k: float | None = None,
) -> tuple[str, int, float, float]:
    """Simulate one trade; returns (reason, exit_idx, ref_price, mfe_pct).

    Mirrors the evaluator: entry-bar gap checks then intrabar stop-first on
    ties; later bars: shifted exit_signal at open first, then gap/intrabar.
    Trailing (k*ATR from peak close) replaces the fixed stop when set.
    """
    risk = opens[entry] - stop
    target = opens[entry] + rr * risk if risk > 0 else float("inf")
    cur_stop = stop
    n = len(closes)
    last_bar = min(entry + max_hold - 1, n - 1)
    peak_close = closes[entry]

    def _trail_update(j: int) -> None:
        nonlocal cur_stop, peak_close
        peak_close = max(peak_close, closes[j])
        if trailing_k is not None and not np.isnan(atr[j]):
            cur_stop = max(cur_stop, peak_close - trailing_k * atr[j])

    def _intrabar(j: int) -> tuple[str, float] | None:
        o, h, low = opens[j], highs[j], lows[j]
        if cur_stop > 0 and o <= cur_stop:
            return ("STOP_GAP", o)
        if target > 0 and o >= target:
            return ("TARGET_GAP", o)
        stop_hit = cur_stop > 0 and low <= cur_stop
        target_hit = target > 0 and h >= target
        if stop_hit:
            return ("STOP_LOSS", cur_stop)
        if target_hit:
            return ("TAKE_PROFIT", target)
        return None

    ev = _intrabar(entry)
    if ev is not None:
        mfe = (highs[entry] / opens[entry] - 1.0) * 100.0
        return ev[0], entry, ev[1], mfe
    _trail_update(entry)
    for j in range(entry + 1, last_bar + 1):
        _trail_update(j - 1)
        if exits[j]:
            mfe = (np.max(highs[entry : j + 1]) / opens[entry] - 1.0) * 100.0
            return "SIGNAL_OPEN", j, opens[j], mfe
        ev = _intrabar(j)
        if ev is not None:
            mfe = (np.max(highs[entry : j + 1]) / opens[entry] - 1.0) * 100.0
            return ev[0], j, ev[1], mfe
    mfe = (np.max(highs[entry : last_bar + 1]) / opens[entry] - 1.0) * 100.0
    return "MAX_HOLD", last_bar, closes[last_bar], mfe


def run_phase4(
    frames: dict[str, pd.DataFrame],
    sig_frames: dict[str, pd.DataFrame],
    signals: pd.DataFrame,
    cost: CostModel,
) -> list[dict[str, object]]:
    policies: list[tuple[str, float, int, float | None, bool]] = []
    for rr in (1.0, 1.5, 2.0, 3.0):
        for mh in (3, 5, 10, 20):
            policies.append((f"rr{rr:g}_mh{mh}", rr, mh, None, False))
    for k in (1.5, 2.0, 3.0):
        policies.append((f"trail_k{k:g}_mh10", 2.0, 10, k, True))
    policies.append(("rr2_mh5_fixed5stop", 2.0, 5, None, True))

    # time split on entry dates (first ~2/3 select, last ~1/3 test)
    entry_dates = sorted(pd.Timestamp(d) for d in signals["entry_date"].unique())
    split = entry_dates[int(len(entry_dates) * 2 / 3)]

    per_policy: dict[str, list[dict[str, object]]] = {name: [] for name, *_ in policies}
    for _, r in signals.iterrows():
        ticker = str(r["ticker"])
        pos = int(r["pos"])
        sig = sig_frames[ticker]
        df = frames[ticker]
        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        exits = sig["exit_signal"].to_numpy(dtype=bool)
        atr = df["atr"].to_numpy(dtype=float) if "atr" in df.columns else np.full(len(df), np.nan)
        engine_stop = float(sig["calculated_stop"].iloc[pos])
        fixed_stop = opens[pos] * 0.95
        for name, rr, mh, trail_k, _ in policies:
            stop = fixed_stop if name == "rr2_mh5_fixed5stop" else engine_stop
            reason, _j, ref, mfe = simulate_exit(
                opens,
                highs,
                lows,
                closes,
                exits,
                atr,
                pos,
                stop=stop,
                rr=rr,
                max_hold=mh,
                trailing_k=trail_k,
            )
            gross = ref / opens[pos] - 1.0
            net = net_of_cost(gross, cost)
            per_policy[name].append(
                {
                    "entry_date": pd.Timestamp(r["entry_date"]),
                    "reason": reason,
                    "net": net,
                    "win": net > 0,
                    "target_hit": reason in {"TAKE_PROFIT", "TARGET_GAP"},
                    "mfe": mfe,
                    "gross": gross,
                }
            )

    rows: list[dict[str, object]] = []
    for name, _rr, _mh, _k, _ in policies:
        recs = per_policy[name]
        sel = [x for x in recs if x["entry_date"] <= split]
        tst = [x for x in recs if x["entry_date"] > split]

        def _agg(part: list[dict[str, object]]) -> tuple[float, float, float, float, float]:
            if not part:
                return (0.0,) * 5
            nets = np.asarray([x["net"] for x in part])
            wr = float(np.mean([x["win"] for x in part]))
            hit = float(np.mean([x["target_hit"] for x in part]))
            capture = float(
                np.mean(
                    [(x["gross"] * 100.0) / x["mfe"] for x in part if x["mfe"] and x["mfe"] > 0.1]
                )
            )
            return float(nets.mean()), wr, hit, capture, float(len(part))

        sm, swr, shit, scap, sn = _agg(sel)
        tm, twr, thit, tcap, tn = _agg(tst)
        rows.append(
            {
                "policy": name,
                "select_mean_net": sm,
                "select_wr": swr,
                "test_mean_net": tm,
                "test_wr": twr,
                "test_target_hit": thit,
                "test_mfe_capture": tcap,
                "select_n": sn,
                "test_n": tn,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", type=str, default="all", choices=("0", "1", "2", "3", "4", "all")
    )
    parser.add_argument("--cache-dir", type=str, default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--reference-csv", type=str, default=str(REFERENCE_CSV))
    parser.add_argument("--output-dir", type=str, default=str(REPO_ROOT / "results"))
    parser.add_argument("--no-parity", action="store_true", help="skip parity anchor (debug only)")
    parser.add_argument("--panel-parquet", type=str, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.output_dir)
    params = StrategyParams.conservative()
    cost = CostModel()
    backtester = Backtester(strategy_params=params, target_rr=2.0, cost_model=cost)

    print("building signal universe from cache (this recomputes all precalculated signals)...")
    signals, frames, _sig_frames = build_signal_universe(cache_dir, backtester)
    print(f"  signals={len(signals)} tickers={len(frames)}")

    if not args.no_parity:
        ref = Path(args.reference_csv)
        assert_parity(signals, ref)
        print(f"  parity anchor OK: regenerated set == {ref.name} ({len(signals)} rows)")

    write_reproducibility(cache_dir, out_dir / "expE_reproducibility.txt", args)

    if args.phase in {"0", "all"}:
        print("running phase 0 (measurement audit)...")
        p0 = run_phase0(signals, frames, cost)
        _write_csv(p0.rows, out_dir / "expE_faz0_matched_baseline.csv")
        _write_csv(p0.summary, out_dir / "expE_faz0_metrics.csv")
        for row in p0.summary:
            print(f"  {row['metric']}: {row['value']}")

    if args.phase in {"1", "all"}:
        print("running phase 1 (feature panel + IC matrix)...")
        panel = build_feature_panel(frames, signals, params)
        panel_path = Path(args.panel_parquet or (out_dir / "expE_faz1_feature_panel.parquet"))
        panel_path.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(panel_path)
        print(f"  panel rows={len(panel)} -> {panel_path.name}")
        ic = run_phase1(panel)
        ic_path = out_dir / "expE_faz1_ic_matrix.csv"
        ic.to_csv(ic_path, index=False)
        print(f"  IC rows={len(ic)} -> {ic_path.name}")
        sig = ic[ic["fdr_significant"] & ic["material"]]
        if len(sig):
            print("  material + FDR-significant features:")
            for _, r in sig.sort_values(["basis", "condition", "horizon", "ic"]).iterrows():
                print(
                    f"    {r['basis']} {r['condition']:>13} h={r['horizon']:>2} "
                    f"{r['feature']:<22} IC={r['ic']:+.3f} (n={int(r['n'])})"
                )
        else:
            print("  no feature is both material (|IC|>=0.02) and FDR-significant")

    if args.phase in {"2", "all"}:
        print("running phase 2 (gate & threshold A/B; ~8 regenerations)...")
        p2 = run_phase2(frames, _sig_frames, signals, params)
        _write_csv(p2, out_dir / "expE_faz2_gate_ab.csv")
        for row in p2:
            print(
                f"  {row['variant']:<26} {row['subset']:<15} n={row['n']:>4} "
                f"mean={row['mean_fwd5_ii']:+.4f} up={row['up_rate']:.3f}"
                + ("  [indicative]" if row["indicative"] else "")
            )

    if args.phase in {"3", "all"}:
        print("running phase 3 (fill timing decomposition)...")
        p3 = run_phase3(frames, signals)
        _write_csv(p3, out_dir / "expE_faz3_fill_ab.csv")
        df3 = pd.DataFrame(p3)
        print(
            f"  n={len(df3)}  overnight gap mean={df3['overnight_gap_pct'].mean():+.3f}%  "
            f"day1 drift mean={df3['day1_drift_pct'].mean():+.3f}%"
        )
        for label, mask in (
            ("rsi<30", df3["rsi"] < 30),
            ("bb_above_upper", df3["bb_above_upper"] == 1),
            ("golden_cross", df3["golden_cross"] == 1),
            ("macd_bull", df3["macd_bull"] == 1),
        ):
            sub = df3[mask]
            if len(sub) >= 5:
                print(
                    f"  {label:<15} n={len(sub):>3} gap={sub['overnight_gap_pct'].mean():+.3f}% "
                    f"drift={sub['day1_drift_pct'].mean():+.3f}%"
                )

    if args.phase in {"4", "all"}:
        print("running phase 4 (exit surface)...")
        p4 = run_phase4(frames, _sig_frames, signals, cost)
        _write_csv(p4, out_dir / "expE_faz4_exit_surface.csv")
        df4 = pd.DataFrame(p4).sort_values("test_mean_net", ascending=False)
        print("  policy (test split, son ~1/3):")
        for _, r in df4.iterrows():
            print(
                f"  {r['policy']:<20} sel_mean={r['select_mean_net']:+.4f} "
                f"test_mean={r['test_mean_net']:+.4f} test_wr={r['test_wr']:.3f} "
                f"hit={r['test_target_hit']:.3f} capture={r['test_mfe_capture']:.3f}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
