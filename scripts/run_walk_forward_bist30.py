"""Multi-ticker walk-forward scan on BIST30 with StrategyParams.conservative().

Usage (from repo root):
    python scripts/run_walk_forward_bist30.py
    python scripts/run_walk_forward_bist30.py --limit 5
    python scripts/run_walk_forward_bist30.py --force-download

Outputs:
    results/walk_forward_bist30_conservative.csv
    Console summary table + universe aggregates
"""

from __future__ import annotations

import argparse
import copy
import csv
import statistics
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import yfinance as yf

from bist_bot.config.settings import settings
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.engine_filters import calculate_score_and_reasons
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.regime import check_momentum_confirmation
from bist_bot.strategy.scoring import (
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)
from bist_bot.validation import WalkForwardValidator

warnings.filterwarnings("ignore")

# Approximate current BIST30 constituents (Yahoo Finance .IS symbols).
# Composition changes over time; update when the index rebalances.
BIST30_TICKERS: list[str] = [
    "AKBNK.IS",
    "ARCLK.IS",
    "ASELS.IS",
    "ASTOR.IS",
    "BIMAS.IS",
    "EKGYO.IS",
    "ENKAI.IS",
    "EREGL.IS",
    "FROTO.IS",
    "GARAN.IS",
    "GUBRF.IS",
    "HEKTS.IS",
    "ISCTR.IS",
    "KCHOL.IS",
    "KONTR.IS",
    "KOZAA.IS",
    "KOZAL.IS",
    "KRDMD.IS",
    "ODAS.IS",
    "OYAKC.IS",
    "PETKM.IS",
    "PGSUS.IS",
    "SAHOL.IS",
    "SASA.IS",
    "SISE.IS",
    "TAVHL.IS",
    "TCELL.IS",
    "THYAO.IS",
    "TOASO.IS",
    "TUPRS.IS",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_CSV = REPO_ROOT / "results" / "walk_forward_bist30_conservative.csv"
DEFAULT_CHASE_DIAGNOSE_CSV = REPO_ROOT / "results" / "chase_diagnose.csv"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "bist_bot" / "wf_data"


def _normalize_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame | None:
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
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(out.columns)):
        return None
    out = out[list(required)].dropna(how="any")
    if out.empty:
        return None
    return out


def _cache_path(cache_dir: Path, ticker: str, period: str) -> Path:
    safe = ticker.replace(".", "_").replace("/", "_")
    return cache_dir / f"{safe}_{period}.parquet"


def load_or_download(
    ticker: str,
    *,
    period: str,
    cache_dir: Path,
    force_download: bool,
    sleep_seconds: float,
) -> pd.DataFrame | None:
    """Load OHLCV from local cache or download via yfinance."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, ticker, period)

    if path.exists() and not force_download:
        try:
            cached = pd.read_parquet(path)
            normalized = _normalize_ohlcv(cached)
            if normalized is not None and len(normalized) >= 50:
                return normalized
        except Exception as exc:
            print(f"  cache read failed for {ticker}: {type(exc).__name__}: {exc}")

    try:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        df = _normalize_ohlcv(raw)
        if df is None or df.empty:
            return None
        try:
            df.to_parquet(path)
        except Exception as exc:
            # Cache write is best-effort (parquet engine may be missing).
            print(f"  cache write skipped for {ticker}: {type(exc).__name__}")
            try:
                csv_path = path.with_suffix(".csv")
                df.to_csv(csv_path)
            except Exception:
                pass
        return df
    except Exception as exc:
        print(f"  download failed for {ticker}: {type(exc).__name__}: {exc}")
        return None


def _load_csv_fallback(cache_dir: Path, ticker: str, period: str) -> pd.DataFrame | None:
    csv_path = _cache_path(cache_dir, ticker, period).with_suffix(".csv")
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        return _normalize_ohlcv(df)
    except Exception:
        return None


def evaluate_ticker(
    ticker: str,
    df: pd.DataFrame,
    wf: WalkForwardValidator,
) -> dict[str, object]:
    """Run walk-forward and return a flat result row."""
    try:
        result = wf.run(ticker, df)
    except Exception as exc:
        return {
            "ticker": ticker,
            "status": f"ERROR:{type(exc).__name__}",
            "windows": 0,
            "oos_mean_return": None,
            "oos_max_dd": None,
            "oos_median_return": None,
            "oos_mean_sharpe": None,
            "is_mean_return": None,
            "has_overfitting_warning": False,
            "buy_threshold": wf.strategy_params.buy_threshold,
            "total_oos_trades": 0,
            "counter_trend_multiplier": wf.strategy_params.counter_trend_multiplier,
            "obv_divergence_cap": wf.strategy_params.obv_divergence_cap,
            "rows": len(df),
        }

    if result is None:
        return {
            "ticker": ticker,
            "status": "NO_WINDOWS",
            "windows": 0,
            "oos_mean_return": None,
            "oos_max_dd": None,
            "oos_median_return": None,
            "oos_mean_sharpe": None,
            "is_mean_return": None,
            "has_overfitting_warning": False,
            "buy_threshold": wf.strategy_params.buy_threshold,
            "total_oos_trades": 0,
            "counter_trend_multiplier": wf.strategy_params.counter_trend_multiplier,
            "obv_divergence_cap": wf.strategy_params.obv_divergence_cap,
            "rows": len(df),
        }

    return {
        "ticker": ticker,
        "status": "OK",
        "windows": len(result.windows),
        "oos_mean_return": round(result.oos_aggregate["mean_total_return_pct"], 4),
        "oos_max_dd": round(result.oos_aggregate["mean_max_drawdown_pct"], 4),
        "oos_median_return": round(result.oos_aggregate["median_total_return_pct"], 4),
        "oos_mean_sharpe": round(result.oos_aggregate["mean_sharpe_ratio"], 4),
        "is_mean_return": round(result.is_aggregate["mean_total_return_pct"], 4),
        "has_overfitting_warning": bool(result.has_overfitting_warning),
        "buy_threshold": wf.strategy_params.buy_threshold,
        "total_oos_trades": sum(w.test_trades for w in result.windows),
        "counter_trend_multiplier": wf.strategy_params.counter_trend_multiplier,
        "obv_divergence_cap": wf.strategy_params.obv_divergence_cap,
        "rows": len(df),
    }


def _fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "YES" if value else "no"
    if isinstance(value, int | float):
        return f"{float(value):.{digits}f}"
    return str(value)


def print_summary(rows: list[dict[str, object]]) -> None:
    ok_rows = [r for r in rows if r["status"] == "OK"]
    print("=" * 100)
    print(
        f"{'Ticker':<12} {'St':<12} {'Win':>4} {'Trades':>6} {'OOS mean%':>10} {'OOS med%':>10} "
        f"{'OOS DD%':>10} {'IS mean%':>10} {'Overfit':>8}"
    )
    print("-" * 100)
    for row in rows:
        print(
            f"{row['ticker']!s:<12} {row['status']!s:<12} {int(row['windows']):>4} {int(row.get('total_oos_trades', 0)):>6} "
            f"{_fmt(row['oos_mean_return']):>10} {_fmt(row['oos_median_return']):>10} "
            f"{_fmt(row['oos_max_dd']):>10} {_fmt(row['is_mean_return']):>10} "
            f"{_fmt(row['has_overfitting_warning']):>8}"
        )
    print("=" * 100)

    if not ok_rows:
        print("Universe summary: no successful walk-forward results.")
        return

    oos_vals = [float(r["oos_mean_return"]) for r in ok_rows if r["oos_mean_return"] is not None]
    positive = sum(1 for v in oos_vals if v > 0)
    overfit = sum(1 for r in ok_rows if r["has_overfitting_warning"])
    n = len(ok_rows)
    median_oos = statistics.median(oos_vals) if oos_vals else 0.0
    mean_oos = statistics.mean(oos_vals) if oos_vals else 0.0
    print("Universe summary (status=OK only)")
    print(f"  tickers_ok          : {n}/{len(rows)}")
    print(f"  median OOS return % : {median_oos:.2f}")
    print(f"  mean OOS return %   : {mean_oos:.2f}")
    print(f"  positive OOS share  : {100.0 * positive / n:.1f}% ({positive}/{n})")
    print(f"  overfitting share   : {100.0 * overfit / n:.1f}% ({overfit}/{n})")
    # Top / bottom 5 by OOS mean
    ranked = sorted(ok_rows, key=lambda r: float(r["oos_mean_return"] or 0.0), reverse=True)
    print("  top OOS             : " + ", ".join(
        f"{r['ticker']}({float(r['oos_mean_return']):.1f}%)" for r in ranked[:5]
    ))
    print("  bottom OOS          : " + ", ".join(
        f"{r['ticker']}({float(r['oos_mean_return']):.1f}%)" for r in ranked[-5:]
    ))


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "status",
        "windows",
        "oos_mean_return",
        "oos_median_return",
        "oos_max_dd",
        "oos_mean_sharpe",
        "is_mean_return",
        "has_overfitting_warning",
        "buy_threshold",
        "total_oos_trades",
        "counter_trend_multiplier",
        "obv_divergence_cap",
        "gates",
        "rows",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def diagnose_chase_for_window(
    ticker: str,
    window_idx: int,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    params: StrategyParams,
    log_rows: list[dict[str, object]],
) -> tuple[int, int, int, int, int, int, int, int]:
    """Analyze all test rows in a window for H3 chase, H4 divergence, and H6 mtf confluence."""
    full_df = pd.concat([train_df, test_df])
    enriched_full = TechnicalIndicators.add_all(full_df)

    train_len = len(train_df)
    chase_candidates = 0
    chase_high = 0
    h3_capped = 0
    obv_trend_notnull = 0
    h4_long_fired = 0
    h4_short_fired = 0
    h6_confluence_total = 0
    h6_confluence_neutralized = 0
    h6_kill_disabled = 0

    slope_lookback = int(getattr(params, "slope_lookback", 40))
    ema_col = f"ema_{settings.EMA_LONG}"

    def _slope(row_idx: int, col: str) -> tuple[int, float]:
        if (
            col not in enriched_full.columns
            or row_idx < slope_lookback
        ):
            return 0, 0.0
        cur = enriched_full[col].iloc[row_idx]
        prev = enriched_full[col].iloc[row_idx - slope_lookback]
        if pd.isna(cur) or pd.isna(prev):
            return 0, 0.0
        diff = float(cur) - float(prev)
        if diff > 0:
            return 1, diff
        if diff < 0:
            return -1, diff
        return 0, diff

    # Count rows where obv_trend has a real value (not missing) in the test portion of enriched_full.
    # FLAT is a real value (the OBV is flat/neutral), so it counts.
    if "obv_trend" in enriched_full.columns and len(test_df) > 0:
        obv_series = enriched_full["obv_trend"].iloc[train_len : train_len + len(test_df)]
        obv_trend_notnull = sum(
            1
            for v in obv_series
            if v is not None and str(v).strip().lower() not in ("", "nan", "none")
        )

    for offset in range(len(test_df)):
        row_idx = train_len + offset
        row = enriched_full.iloc[row_idx]

        bb_pos = row.get("bb_position")
        cci_raw = row.get("cci")
        cci_val = float(cci_raw) if pd.notna(cci_raw) else None
        dist_resist_raw = row.get("dist_to_resistance_pct")
        dist_resist = (
            float(dist_resist_raw) if pd.notna(dist_resist_raw) else None
        )

        overextended_long = (
            bb_pos == "ABOVE_UPPER"
            or (cci_val is not None and cci_val > params.chase_cci_threshold)
            or (
                dist_resist is not None
                and dist_resist < params.chase_resist_pct
            )
        )

        df_so_far = enriched_full.iloc[: row_idx + 1]
        if len(df_so_far) < 50:
            continue

        last = enriched_full.iloc[row_idx]
        prev = enriched_full.iloc[row_idx - 1]

        # H6: SMA20 / EMA-long slope contradiction (MTF confluence block).
        # Counted across every test row — independent of the scoring pipeline.
        # Operationally: h6_confluence_total == n barrier crossings in the test
        # window; h6_confluence_neutralized == those crossings where the gate
        # would have forced regime → SIDEWAYS.
        sma20_dir, sma20_diff = _slope(row_idx, "sma_20")
        ema_dir, _ema_diff = _slope(row_idx, ema_col)
        h6_contradiction = (
            sma20_dir != 0
            and ema_dir != 0
            and sma20_dir != ema_dir
        )
        if h6_contradiction:
            h6_confluence_total += 1
            if params.mtf_confluence_block_enabled:
                h6_confluence_neutralized += 1
            else:
                h6_kill_disabled += 1

        # Pre-H4 raw score (H4 gate disabled to see raw strength)
        params_off = copy.deepcopy(params)
        params_off.obv_divergence_block_enabled = False

        def score_mom_off(lst: pd.Series, pr: pd.Series, df: pd.DataFrame = None, params_off=params_off) -> tuple[float, list[str]]:
            return score_momentum(params_off, lst, pr)

        def score_tr_off(lst: pd.Series, pr: pd.Series, df: pd.DataFrame = None, params_off=params_off) -> tuple[float, list[str]]:
            return score_trend(params_off, lst, pr, df)

        def score_vol_off(lst: pd.Series, pr: pd.Series, df: pd.DataFrame = None, params_off=params_off) -> tuple[float, list[str]]:
            return score_volume(params_off, lst, pr)

        def score_struct_off(lst: pd.Series, df: pd.DataFrame = None, params_off=params_off) -> tuple[float, list[str]]:
            return score_structure(params_off, lst)

        res_off = calculate_score_and_reasons(
            params_off,
            ticker,
            df_so_far,
            last=last,
            prev=prev,
            momentum_scorer=score_mom_off,
            trend_scorer=score_tr_off,
            volume_scorer=score_vol_off,
            structure_scorer=score_struct_off,
            momentum_checker=check_momentum_confirmation,
        )
        if res_off is None:
            continue

        raw_score, _, _ = res_off

        # H4 divergence check on ALL test rows:
        _obv = last.get("obv_trend", "FLAT")
        _pv = last.get("price_volume_direction", "NONE")

        # obv_down / bearish_pv for long
        obv_down = _obv == "DOWN"
        bearish_pv = _pv == "BEARISH_CONFIRMATION"
        if (obv_down or bearish_pv) and raw_score > 0:
            h4_long_fired += 1

        # obv_up / bullish_pv for short
        obv_up = _obv == "UP"
        bullish_pv = _pv == "BULLISH_CONFIRMATION"
        if (obv_up or bullish_pv) and raw_score < 0:
            h4_short_fired += 1

        # Now check if this row is a chase candidate (overextended and raw_score > buy_threshold)
        if not overextended_long:
            continue

        chase_candidates += 1

        if raw_score <= params.buy_threshold:
            continue

        chase_high += 1

        # Capped score
        params_on = copy.deepcopy(params)
        params_on.chase_block_enabled = True

        def score_mom_on(lst: pd.Series, pr: pd.Series, df: pd.DataFrame = None, params_on=params_on) -> tuple[float, list[str]]:
            return score_momentum(params_on, lst, pr)

        def score_tr_on(lst: pd.Series, pr: pd.Series, df: pd.DataFrame = None, params_on=params_on) -> tuple[float, list[str]]:
            return score_trend(params_on, lst, pr, df)

        def score_vol_on(lst: pd.Series, pr: pd.Series, df: pd.DataFrame = None, params_on=params_on) -> tuple[float, list[str]]:
            return score_volume(params_on, lst, pr)

        def score_struct_on(lst: pd.Series, df: pd.DataFrame = None, params_on=params_on) -> tuple[float, list[str]]:
            return score_structure(params_on, lst)

        res_on = calculate_score_and_reasons(
            params_on,
            ticker,
            df_so_far,
            last=last,
            prev=prev,
            momentum_scorer=score_mom_on,
            trend_scorer=score_tr_on,
            volume_scorer=score_vol_on,
            structure_scorer=score_struct_on,
            momentum_checker=check_momentum_confirmation,
        )

        if res_on is None:
            capped_score = 0.0
        else:
            capped_score, _, _ = res_on

        if capped_score < params.buy_threshold:
            h3_capped += 1

        log_rows.append(
            {
                "ticker": ticker,
                "window_idx": window_idx,
                "date": str(last.name),
                "bb_position": str(bb_pos),
                "cci": float(cci_val) if cci_val is not None else None,
                "dist_to_resistance_pct": (
                    float(dist_resist) if dist_resist is not None else None
                ),
                "raw_score": float(raw_score),
                "capped_score": float(capped_score),
                "capped": "YES" if capped_score < raw_score else "no",
                "obv_trend_notnull": obv_trend_notnull,
                "h4_long_fired": h4_long_fired,
                "h4_short_fired": h4_short_fired,
                "h6_confluence_total": h6_confluence_total,
                "h6_confluence_neutralized": h6_confluence_neutralized,
                "h6_contradiction": h6_contradiction,
                "sma20_slope_diff": sma20_diff,
                "ema_long_slope_dir": ema_dir,
            }
        )

    return (
        chase_candidates,
        chase_high,
        h3_capped,
        obv_trend_notnull,
        h4_long_fired,
        h4_short_fired,
        h6_confluence_neutralized,
        h6_confluence_total,
    )


def write_chase_diagnose_csv(
    rows: list[dict[str, object]], path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "window_idx",
        "date",
        "bb_position",
        "cci",
        "dist_to_resistance_pct",
        "raw_score",
        "capped_score",
        "capped",
        "obv_trend_notnull",
        "h4_long_fired",
        "h4_short_fired",
        "h6_confluence_total",
        "h6_confluence_neutralized",
        "h6_contradiction",
        "sma20_slope_diff",
        "ema_long_slope_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BIST30 conservative walk-forward scan")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only first N tickers (0 = all BIST30). Useful for smoke tests.",
    )
    parser.add_argument(
        "--period",
        type=str,
        default="3y",
        help="yfinance period string (default: 3y)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(DEFAULT_CACHE_DIR),
        help=f"Local OHLCV cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_RESULTS_CSV),
        help=f"CSV output path (default: {DEFAULT_RESULTS_CSV})",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Ignore cache and re-download all tickers",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.35,
        help="Seconds to sleep between yfinance downloads (rate-limit friendly)",
    )
    parser.add_argument(
        "--counter-trend-multiplier",
        type=float,
        default=0.0,
        help="Override counter_trend_multiplier on the conservative profile (default: 0.0 = use conservative default)",
    )
    parser.add_argument(
        "--slope-lookback",
        type=int,
        default=None,
        help="Override slope_lookback on the conservative profile (default: None = use conservative default of 5)",
    )
    parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Kill-switch: disable H1+H3 gates (counter_trend_multiplier=1.0, chase_block_enabled=False). "
        "Overrides --counter-trend-multiplier. Output saved to *_gates_OFF.csv.",
    )
    parser.add_argument(
        "--diagnose-chase",
        action="store_true",
        help="Run diagnostic check on H3 chase overextended long condition",
    )
    parser.add_argument(
        "--chase-diagnose-csv",
        type=str,
        default=str(DEFAULT_CHASE_DIAGNOSE_CSV),
        help=f"CSV output for chase diagnostics (default: {DEFAULT_CHASE_DIAGNOSE_CSV})",
    )
    parser.add_argument(
        "--obv-divergence-cap",
        type=float,
        default=None,
        help="Override obv_divergence_cap on the conservative profile (default: None = use conservative default)",
    )
    parser.add_argument(
        "--buy-threshold",
        type=float,
        default=None,
        help="Override buy_threshold on the conservative profile",
    )
    parser.add_argument(
        "--mtf-confluence-block-enabled",
        dest="mtf_confluence_block_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Override mtf_confluence_block_enabled on the conservative profile. "
            "When True, rows with SMA20/EMA-long slope contradiction force regime → SIDEWAYS. "
            "Default: True. --no-mtf-confluence-block-enabled disables it (sweep comparison). "
            "Output saved to *_h6_off.csv when disabled."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tickers = list(BIST30_TICKERS)
    if args.limit and args.limit > 0:
        tickers = tickers[: args.limit]

    params = StrategyParams.conservative()
    if args.buy_threshold is not None:
        params.buy_threshold = args.buy_threshold
    params.counter_trend_multiplier = args.counter_trend_multiplier
    if args.slope_lookback is not None:
        params.slope_lookback = args.slope_lookback
    if args.obv_divergence_cap is not None:
        params.obv_divergence_cap = args.obv_divergence_cap
    if args.mtf_confluence_block_enabled is not None:
        params.mtf_confluence_block_enabled = bool(args.mtf_confluence_block_enabled)
    gates_enabled = not args.no_gates
    if args.no_gates:
        params.counter_trend_multiplier = 1.0
        params.chase_block_enabled = False
    output_path = Path(args.output)
    if args.buy_threshold is not None and args.output == str(DEFAULT_RESULTS_CSV):
        output_path = REPO_ROOT / "results" / f"walk_forward_bist30_conservative_bt{int(args.buy_threshold)}.csv"
    elif args.no_gates and args.output == str(DEFAULT_RESULTS_CSV):
        output_path = REPO_ROOT / "results" / "walk_forward_bist30_conservative_gates_OFF.csv"
    elif args.obv_divergence_cap is not None and args.output == str(DEFAULT_RESULTS_CSV):
        output_path = REPO_ROOT / "results" / f"walk_forward_bist30_h4_cap{int(args.obv_divergence_cap)}.csv"
    elif args.slope_lookback is not None and args.output == str(DEFAULT_RESULTS_CSV):
        output_path = REPO_ROOT / "results" / f"walk_forward_bist30_h2_sl{args.slope_lookback}.csv"
    elif (
        args.mtf_confluence_block_enabled is False
        and args.output == str(DEFAULT_RESULTS_CSV)
    ):
        output_path = REPO_ROOT / "results" / "walk_forward_bist30_h6_off.csv"
    cache_dir = Path(args.cache_dir)
    wf = WalkForwardValidator(
        train_window=252,
        test_window=63,
        step_size=63,
        commission_bps=2.0,
        slippage_bps=5.0,
        initial_capital=100_000.0,
        strategy_params=params,
    )

    print(
        f"BIST30 walk-forward scan (StrategyParams.conservative, "
        f"counter_trend_multiplier={params.counter_trend_multiplier}, "
        f"gates={'ON' if gates_enabled else 'OFF'}, "
        f"slope_lookback={params.slope_lookback}, "
        f"mtf_confluence_block={'ON' if params.mtf_confluence_block_enabled else 'OFF'})"
    )
    print(
        f"  tickers={len(tickers)}  period={args.period}  "
        f"train/test/step={wf.train_window}/{wf.test_window}/{wf.step_size}"
    )
    print(
        f"  costs: commission_bps={wf.commission_bps} slippage_bps={wf.slippage_bps}  "
        f"cache={cache_dir}"
    )
    print(
        f"  params: buy={params.buy_threshold} sell={params.sell_threshold} "
        f"sideways={params.sideways_score_multiplier} rsi_x={params.score_rsi_extreme} "
        f"counter_trend_multiplier={params.counter_trend_multiplier}"
    )
    print("=" * 100)

    rows: list[dict[str, object]] = []
    chase_rows: list[dict[str, object]] = []
    tot_candidates = 0
    tot_high = 0
    tot_capped = 0
    tot_obv_notnull = 0
    tot_h4_fired = 0
    tot_h4_short_fired = 0
    tot_h6_total = 0
    tot_h6_neutralized = 0
    last_processed_df = None

    for idx, ticker in enumerate(tickers, start=1):
        print(f"[{idx}/{len(tickers)}] {ticker}")
        df = load_or_download(
            ticker,
            period=args.period,
            cache_dir=cache_dir,
            force_download=args.force_download,
            sleep_seconds=float(args.sleep),
        )
        if df is None:
            # Try CSV fallback if parquet failed earlier
            df = _load_csv_fallback(cache_dir, ticker, args.period)
        if df is None or len(df) < (wf.train_window + wf.test_window):
            print(f"  skip: insufficient data (rows={0 if df is None else len(df)})")
            rows.append(
                {
                    "ticker": ticker,
                    "status": "INSUFFICIENT_DATA",
                    "windows": 0,
                    "oos_mean_return": None,
                    "oos_max_dd": None,
                    "oos_median_return": None,
                    "oos_mean_sharpe": None,
                    "is_mean_return": None,
                    "has_overfitting_warning": False,
                    "counter_trend_multiplier": args.counter_trend_multiplier,
                    "gates": "ON" if gates_enabled else "OFF",
                    "rows": 0 if df is None else len(df),
                }
            )
            continue

        # Avoid sleeping again when data came from cache: only sleep on download path
        # is already handled inside load_or_download.
        row = evaluate_ticker(ticker, df, wf)
        row["gates"] = "ON" if gates_enabled else "OFF"
        rows.append(row)
        print(
            f"  status={row['status']} windows={row['windows']} "
            f"OOS={_fmt(row['oos_mean_return'])}% IS={_fmt(row['is_mean_return'])}% "
            f"overfit={_fmt(row['has_overfitting_warning'])} "
            f"ctm={row.get('counter_trend_multiplier', 'n/a')}"
        )
        last_processed_df = df

        if args.diagnose_chase:
            t_candidates = 0
            t_high = 0
            t_capped = 0
            t_obv_notnull = 0
            t_h4_fired = 0
            t_h4_short_fired = 0
            t_h6_total = 0
            t_h6_neutralized = 0
            windows = wf.build_windows(df)
            for w_idx, (train_df, test_df) in enumerate(windows, start=1):
                (
                    c, h, cap, obv_nn, h4f, h4sf, h6n, h6t,
                ) = diagnose_chase_for_window(
                    ticker, w_idx, train_df, test_df, params, chase_rows
                )
                t_candidates += c
                t_high += h
                t_capped += cap
                t_obv_notnull += obv_nn
                t_h4_fired += h4f
                t_h4_short_fired += h4sf
                t_h6_total += h6t
                t_h6_neutralized += h6n
            tot_candidates += t_candidates
            tot_high += t_high
            tot_capped += t_capped
            tot_obv_notnull += t_obv_notnull
            tot_h4_fired += t_h4_fired
            tot_h4_short_fired += t_h4_short_fired
            tot_h6_total += t_h6_total
            tot_h6_neutralized += t_h6_neutralized
            print(
                f"  [diagnose-chase] candidates={t_candidates} "
                f"high_score={t_high} capped={t_capped} "
                f"obv_trend_notnull={t_obv_notnull} "
                f"h4_long_fired={t_h4_fired} h4_short_fired={t_h4_short_fired} "
                f"h6_total={t_h6_total} h6_neutralized={t_h6_neutralized}"
            )

    write_csv(rows, output_path)
    print_summary(rows)
    print(f"CSV written: {output_path}")

    if args.diagnose_chase:
        write_chase_diagnose_csv(chase_rows, Path(args.chase_diagnose_csv))
        print("=" * 100)
        print("CHASE DIAGNOSTICS SUMMARY")
        print("-" * 100)
        print(f"Total chase_candidate_rows (all tickers): {tot_candidates}")
        print(f"Total chase_high_score_rows             : {tot_high}")
        print(f"Total h3_actually_capped_rows           : {tot_capped}")
        print(f"Total obv_trend_notnull (test window)   : {tot_obv_notnull}")
        print(f"Total h4_long_fired (divergence+raw>0) : {tot_h4_fired}")
        print(f"Total h4_short_fired (divergence+raw<0): {tot_h4_short_fired}")
        print(f"Total h6_contradiction_rows           : {tot_h6_total}")
        print(f"Total h6_confluence_neutralized        : {tot_h6_neutralized}")
        if tot_h6_total > 0 and tot_h6_neutralized == 0:
            print("DECISION H6: WF verisinde celiski VAR ama notr'e dusurulmedi - gate kapali olabilir.")
        elif tot_h6_neutralized > 0:
            print(
                f"DECISION H6: {tot_h6_neutralized}/{tot_h6_total} celiskili satir "
                f"regime notr'e dusuruldu (sma20/ema200 egim zit)"
            )
        print("-" * 100)
        if tot_candidates == 0:
            print("DECISION: KOK (3) veya (2): WF verisinde chase olayi YOK. Birim test sahte-pozitif.")
            if last_processed_df is not None:
                enriched_sample = TechnicalIndicators.add_all(last_processed_df.head(55))
                print("\nSample Enriched Columns:")
                print(list(enriched_sample.columns))
                print("\nSample Row values (last row of enriched):")
                print(enriched_sample.iloc[-1].to_dict())
        elif tot_candidates > 0 and tot_high == 0:
            print("DECISION: KOK (1): chase var ama conservative esigi (25) onu zaten eliyor; H3 redundant. H3 kapatilabilir, zararsiz.")
        elif tot_high > 0 and tot_capped == 0:
            print("DECISION: KOK (3): chase+yuksek skor var ama H3 cap'lemiyor -> alan adi / kosul uyusmazligi, H3 entegrasyonda OLU.")
        elif tot_capped > 0:
            print("DECISION: H3 cap'liyor ama OOS degismedi -> H3 cap'liyor ama o pencereler zaten trade edilmiyordu / aggregate'e girmiyordu; o zaman gercekten redundant, H3 kapatilabilir.")
        print("=" * 100)
        print(f"Chase diagnose CSV written: {args.chase_diagnose_csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
