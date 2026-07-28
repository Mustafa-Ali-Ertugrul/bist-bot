"""Cost-stress walk-forward on BIST30 + robust live watchlist builder.

Compares base-case WF results (commission=2bps, slippage=5bps) against a
harsher cost regime (commission=5bps, slippage=15bps) using the same
``StrategyParams.conservative()`` profile and day-based walk-forward windows.

Usage (from repo root):
    python scripts/run_wf_cost_stress.py
    python scripts/run_wf_cost_stress.py --limit 5
    python scripts/run_wf_cost_stress.py --base-csv results/walk_forward_bist30_conservative.csv

Outputs:
    results/walk_forward_bist30_cost_stress.csv
    results/robust_watchlist.csv
"""

from __future__ import annotations

import argparse
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
from bist_bot.strategy.params import StrategyParams
from bist_bot.validation import WalkForwardValidator

warnings.filterwarnings("ignore")

# Keep in sync with scripts/run_walk_forward_bist30.py
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
DEFAULT_BASE_CSV = REPO_ROOT / "results" / "walk_forward_bist30_conservative.csv"
DEFAULT_STRESS_CSV = REPO_ROOT / "results" / "walk_forward_bist30_cost_stress.csv"
DEFAULT_WATCHLIST_CSV = REPO_ROOT / "results" / "robust_watchlist.csv"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "bist_bot" / "wf_data"

STRESS_COMMISSION_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
ROBUST_MAX_DD = -10.0  # worse (more negative) than this fails


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
    return None if out.empty else out


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
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, ticker, period)

    if path.exists() and not force_download:
        try:
            cached = pd.read_parquet(path)
            normalized = _normalize_ohlcv(cached)
            if normalized is not None and len(normalized) >= 50:
                return normalized
        except Exception as exc:
            print(f"  cache parquet failed {ticker}: {type(exc).__name__}")

    csv_path = path.with_suffix(".csv")
    if csv_path.exists() and not force_download:
        try:
            cached = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            normalized = _normalize_ohlcv(cached)
            if normalized is not None and len(normalized) >= 50:
                return normalized
        except Exception as exc:
            print(f"  cache csv failed {ticker}: {type(exc).__name__}")

    try:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        df = _normalize_ohlcv(raw)
        if df is None:
            return None
        try:
            df.to_parquet(path)
        except Exception:
            try:
                df.to_csv(csv_path)
            except Exception:
                pass
        return df
    except Exception as exc:
        print(f"  download failed {ticker}: {type(exc).__name__}: {exc}")
        return None


def load_base_csv(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        print(f"WARNING: base CSV not found: {path}")
        print("  Run scripts/run_walk_forward_bist30.py first for a full comparison.")
        return {}
    by_ticker: dict[str, dict[str, object]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            by_ticker[ticker] = row
    return by_ticker


def _to_float(value: object, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _count_h4_obv(df: pd.DataFrame, params: StrategyParams) -> dict[str, int]:
    """Count per-ticker H4 + H6 counters for walk-forward CSV diagnostic column.

    obv_trend_notnull: rows where obv_trend column has a real value (not missing).
    h4_long_fired: rows where OBV DOWN or price_volume BEARISH_CONFIRMATION
    (divergence condition present — raw_score check not possible at this level,
    so this is a divergence-frequency proxy; the actual cap only fires on
    long candidates whose raw_score > buy_threshold).
    h4_short_fired: symmetric short divergence (OBV UP or price_volume BULLISH_CONFIRMATION).
    h6_confluence_total: rows where SMA20 slope vs EMA-long slope contradiction is true.
    h6_confluence_neutralized: subset of the above that the gate would have neutralized
    (i.e. mtf_confluence_block_enabled is True and the row is non-degenerate).
    """
    enriched = TechnicalIndicators.add_all(df)
    obv_trend_notnull = 0
    h4_long_fired = 0
    h4_short_fired = 0
    h6_confluence_total = 0
    h6_confluence_neutralized = 0

    slope_lookback = int(getattr(params, "slope_lookback", 40))
    ema_col = f"ema_{settings.EMA_LONG}"
    mtf_block_enabled = bool(getattr(params, "mtf_confluence_block_enabled", True))

    if "sma_20" in enriched.columns and ema_col in enriched.columns:
        sma_series = enriched["sma_20"].reset_index(drop=True)
        ema_series = enriched[ema_col].reset_index(drop=True)
        for i in range(slope_lookback, len(enriched)):
            sma_cur = sma_series.iloc[i]
            sma_prev = sma_series.iloc[i - slope_lookback]
            ema_cur = ema_series.iloc[i]
            ema_prev = ema_series.iloc[i - slope_lookback]
            try:
                if pd.isna(sma_cur) or pd.isna(sma_prev) or pd.isna(ema_cur) or pd.isna(ema_prev):
                    continue
            except (TypeError, ValueError):
                continue
            sma_slope = float(sma_cur) - float(sma_prev)
            ema_slope = float(ema_cur) - float(ema_prev)
            sma_dir = 1 if sma_slope > 0 else (-1 if sma_slope < 0 else 0)
            ema_dir = 1 if ema_slope > 0 else (-1 if ema_slope < 0 else 0)
            if sma_dir != 0 and ema_dir != 0 and sma_dir != ema_dir:
                h6_confluence_total += 1
                if mtf_block_enabled:
                    h6_confluence_neutralized += 1

    obv_series = enriched.get("obv_trend")

    if obv_series is not None and len(enriched) > 0:
        for _, row in enriched.iterrows():
            obv = row.get("obv_trend")
            if obv is not None and str(obv).strip().lower() not in ("", "nan", "none"):
                obv_trend_notnull += 1
            pv = row.get("price_volume_direction")
            if obv == "DOWN" or pv == "BEARISH_CONFIRMATION":
                h4_long_fired += 1
            elif obv == "UP" or pv == "BULLISH_CONFIRMATION":
                h4_short_fired += 1

    return {
        "obv_trend_notnull": obv_trend_notnull,
        "h4_long_fired": h4_long_fired,
        "h4_short_fired": h4_short_fired,
        "h6_confluence_total": h6_confluence_total,
        "h6_confluence_neutralized": h6_confluence_neutralized,
    }


def evaluate_stress(
    ticker: str,
    df: pd.DataFrame,
    wf: WalkForwardValidator,
) -> dict[str, object]:
    try:
        result = wf.run(ticker, df)
    except Exception as exc:
        return {
            "ticker": ticker,
            "status": f"ERROR:{type(exc).__name__}",
            "windows": 0,
            "stress_oos_mean_return": None,
            "stress_oos_max_dd": None,
            "stress_is_mean_return": None,
            "has_overfitting_warning": False,
            "buy_threshold": wf.strategy_params.buy_threshold,
            "total_oos_trades": 0,
            "counter_trend_multiplier": wf.strategy_params.counter_trend_multiplier,
            "obv_trend_notnull": 0,
            "h4_long_fired": 0,
            "h4_short_fired": 0,
            "h6_confluence_total": 0,
            "h6_confluence_neutralized": 0,
            "obv_divergence_cap": wf.strategy_params.obv_divergence_cap,
        }

    if result is None:
        return {
            "ticker": ticker,
            "status": "NO_WINDOWS",
            "windows": 0,
            "stress_oos_mean_return": None,
            "stress_oos_max_dd": None,
            "stress_is_mean_return": None,
            "has_overfitting_warning": False,
            "buy_threshold": wf.strategy_params.buy_threshold,
            "total_oos_trades": 0,
            "counter_trend_multiplier": wf.strategy_params.counter_trend_multiplier,
            "obv_trend_notnull": 0,
            "h4_long_fired": 0,
            "h4_short_fired": 0,
            "h6_confluence_total": 0,
            "h6_confluence_neutralized": 0,
            "obv_divergence_cap": wf.strategy_params.obv_divergence_cap,
        }

    h4_counts = _count_h4_obv(df, wf.strategy_params)
    return {
        "ticker": ticker,
        "status": "OK",
        "windows": len(result.windows),
        "stress_oos_mean_return": round(result.oos_aggregate["mean_total_return_pct"], 4),
        "stress_oos_max_dd": round(result.oos_aggregate["mean_max_drawdown_pct"], 4),
        "stress_is_mean_return": round(result.is_aggregate["mean_total_return_pct"], 4),
        "has_overfitting_warning": bool(result.has_overfitting_warning),
        "buy_threshold": wf.strategy_params.buy_threshold,
        "total_oos_trades": sum(w.test_trades for w in result.windows),
        "counter_trend_multiplier": wf.strategy_params.counter_trend_multiplier,
        "obv_trend_notnull": h4_counts["obv_trend_notnull"],
        "h4_long_fired": h4_counts["h4_long_fired"],
        "h4_short_fired": h4_counts["h4_short_fired"],
        "h6_confluence_total": h4_counts["h6_confluence_total"],
        "h6_confluence_neutralized": h4_counts["h6_confluence_neutralized"],
        "obv_divergence_cap": wf.strategy_params.obv_divergence_cap,
    }


def _fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "YES" if value else "no"
    if isinstance(value, int | float):
        return f"{float(value):.{digits}f}"
    return str(value)


def write_csv(rows: list[dict[str, object]], path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BIST30 cost-stress WF + robust watchlist")
    p.add_argument("--limit", type=int, default=0, help="First N tickers only (0=all)")
    p.add_argument("--period", type=str, default="3y")
    p.add_argument("--cache-dir", type=str, default=str(DEFAULT_CACHE_DIR))
    p.add_argument("--base-csv", type=str, default=str(DEFAULT_BASE_CSV))
    p.add_argument("--stress-csv", type=str, default=str(DEFAULT_STRESS_CSV))
    p.add_argument("--watchlist-csv", type=str, default=str(DEFAULT_WATCHLIST_CSV))
    p.add_argument("--force-download", action="store_true")
    p.add_argument("--sleep", type=float, default=0.35)
    p.add_argument("--commission-bps", type=float, default=STRESS_COMMISSION_BPS)
    p.add_argument("--slippage-bps", type=float, default=STRESS_SLIPPAGE_BPS)
    p.add_argument(
        "--max-dd",
        type=float,
        default=ROBUST_MAX_DD,
        help="Minimum allowed stress OOS max DD (e.g. -10 means DD must be > -10)",
    )
    p.add_argument(
        "--counter-trend-multiplier",
        type=float,
        default=0.0,
        help="Override counter_trend_multiplier on the conservative profile (default: 0.0 = use conservative default)",
    )
    p.add_argument(
        "--slope-lookback",
        type=int,
        default=None,
        help="Override slope_lookback on the conservative profile (default: None = use conservative default of 5)",
    )
    p.add_argument(
        "--no-gates",
        action="store_true",
        help="Kill-switch: disable H1+H3 gates (counter_trend_multiplier=1.0, chase_block_enabled=False). "
        "Overrides --counter-trend-multiplier. Output saved to *_gates_OFF.csv.",
    )
    p.add_argument(
        "--obv-divergence-cap",
        type=float,
        default=None,
        help="Override obv_divergence_cap on the conservative profile (default: None = use conservative default)",
    )
    p.add_argument(
        "--buy-threshold",
        type=float,
        default=None,
        help="Override buy_threshold on the conservative profile",
    )
    p.add_argument(
        "--mtf-confluence-block-enabled",
        dest="mtf_confluence_block_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Override mtf_confluence_block_enabled on the conservative profile (H6). "
            "Default: True. --no-mtf-confluence-block-enabled disables it (sweep comparison)."
            " Output saved to *_h6_off.csv when disabled."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tickers = list(BIST30_TICKERS)
    if args.limit and args.limit > 0:
        tickers = tickers[: args.limit]

    base_map = load_base_csv(Path(args.base_csv))
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
    stress_path = Path(args.stress_csv)
    watchlist_path = Path(args.watchlist_csv)
    if args.buy_threshold is not None:
        if args.stress_csv == str(DEFAULT_STRESS_CSV):
            stress_path = REPO_ROOT / "results" / f"walk_forward_bist30_cost_stress_bt{int(args.buy_threshold)}.csv"
        if args.watchlist_csv == str(DEFAULT_WATCHLIST_CSV):
            watchlist_path = REPO_ROOT / "results" / f"robust_watchlist_bt{int(args.buy_threshold)}.csv"
    else:
        if args.no_gates and args.stress_csv == str(DEFAULT_STRESS_CSV):
            stress_path = REPO_ROOT / "results" / "walk_forward_bist30_cost_stress_gates_OFF.csv"
        elif args.obv_divergence_cap is not None and args.stress_csv == str(DEFAULT_STRESS_CSV):
            stress_path = REPO_ROOT / "results" / f"walk_forward_bist30_cost_stress_h4_cap{int(args.obv_divergence_cap)}.csv"
        elif args.slope_lookback is not None and args.stress_csv == str(DEFAULT_STRESS_CSV):
            stress_path = REPO_ROOT / "results" / f"walk_forward_bist30_cost_stress_h2_sl{args.slope_lookback}.csv"
        elif (
            args.mtf_confluence_block_enabled is False
            and args.stress_csv == str(DEFAULT_STRESS_CSV)
        ):
            stress_path = REPO_ROOT / "results" / "walk_forward_bist30_cost_stress_h6_off.csv"

        if args.no_gates and args.watchlist_csv == str(DEFAULT_WATCHLIST_CSV):
            watchlist_path = REPO_ROOT / "results" / "robust_watchlist_gates_OFF.csv"
        elif args.obv_divergence_cap is not None and args.watchlist_csv == str(DEFAULT_WATCHLIST_CSV):
            watchlist_path = REPO_ROOT / "results" / f"robust_watchlist_h4_cap{int(args.obv_divergence_cap)}.csv"
        elif (
            args.mtf_confluence_block_enabled is False
            and args.watchlist_csv == str(DEFAULT_WATCHLIST_CSV)
        ):
            watchlist_path = REPO_ROOT / "results" / "robust_watchlist_h6_off.csv"
    wf = WalkForwardValidator(
        train_window=252,
        test_window=63,
        step_size=63,
        commission_bps=float(args.commission_bps),
        slippage_bps=float(args.slippage_bps),
        initial_capital=100_000.0,
        strategy_params=params,
    )
    cache_dir = Path(args.cache_dir)

    print("BIST30 cost-stress walk-forward")
    print(
        f"  stress costs: commission_bps={wf.commission_bps} slippage_bps={wf.slippage_bps}"
    )
    print(
        f"  profile=conservative buy={params.buy_threshold} sell={params.sell_threshold} "
        f"sideways={params.sideways_score_multiplier} ctm={params.counter_trend_multiplier} "
        f"gates={'ON' if gates_enabled else 'OFF'}, "
        f"slope_lookback={params.slope_lookback}"
    )
    print(f"  base_csv={args.base_csv}")
    print(f"  robust filters: stress_oos>0, overfit=False, stress_dd>{args.max_dd}")
    print("=" * 110)

    stress_rows: list[dict[str, object]] = []
    for idx, ticker in enumerate(tickers, start=1):
        print(f"[{idx}/{len(tickers)}] {ticker}")
        df = load_or_download(
            ticker,
            period=args.period,
            cache_dir=cache_dir,
            force_download=bool(args.force_download),
            sleep_seconds=float(args.sleep),
        )
        if df is None or len(df) < (wf.train_window + wf.test_window):
            print("  skip: insufficient data")
            stress_rows.append(
                {
                    "ticker": ticker,
                    "status": "INSUFFICIENT_DATA",
                    "windows": 0,
                    "base_oos_mean_return": _to_float(
                        (base_map.get(ticker) or {}).get("oos_mean_return")
                    ),
                    "stress_oos_mean_return": None,
                    "edge_decay": None,
                    "stress_oos_max_dd": None,
                    "stress_is_mean_return": None,
                    "has_overfitting_warning": False,
                    "base_has_overfitting_warning": _to_bool(
                        (base_map.get(ticker) or {}).get("has_overfitting_warning")
                    ),
                    "robust": False,
                    "buy_threshold": params.buy_threshold,
                    "total_oos_trades": 0,
                    "counter_trend_multiplier": args.counter_trend_multiplier,
                    "gates": "ON" if gates_enabled else "OFF",
                    "obv_trend_notnull": 0,
                    "h4_long_fired": 0,
                    "h4_short_fired": 0,
                    "h6_confluence_total": 0,
                    "h6_confluence_neutralized": 0,
                    "obv_divergence_cap": params.obv_divergence_cap,
                    "mtf_confluence_block_enabled": bool(params.mtf_confluence_block_enabled),
                }
            )
            continue

        stress = evaluate_stress(ticker, df, wf)
        base = base_map.get(ticker) or {}
        base_oos = _to_float(base.get("oos_mean_return"))
        stress_oos = _to_float(stress.get("stress_oos_mean_return"))
        edge_decay = None
        if base_oos is not None and stress_oos is not None:
            edge_decay = round(base_oos - stress_oos, 4)

        stress_dd = _to_float(stress.get("stress_oos_max_dd"))
        overfit = bool(stress.get("has_overfitting_warning"))
        robust = (
            stress.get("status") == "OK"
            and stress_oos is not None
            and stress_oos > 0.0
            and not overfit
            and stress_dd is not None
            and stress_dd > float(args.max_dd)
        )

        row = {
            "ticker": ticker,
            "status": stress.get("status"),
            "windows": stress.get("windows", 0),
            "base_oos_mean_return": base_oos,
            "stress_oos_mean_return": stress_oos,
            "edge_decay": edge_decay,
            "stress_oos_max_dd": stress_dd,
            "stress_is_mean_return": stress.get("stress_is_mean_return"),
            "has_overfitting_warning": overfit,
            "base_has_overfitting_warning": _to_bool(base.get("has_overfitting_warning")),
            "robust": robust,
            "counter_trend_multiplier": args.counter_trend_multiplier,
            "gates": "ON" if gates_enabled else "OFF",
            "obv_trend_notnull": int(stress.get("obv_trend_notnull") or 0),
            "h4_long_fired": int(stress.get("h4_long_fired") or 0),
            "h4_short_fired": int(stress.get("h4_short_fired") or 0),
            "h6_confluence_total": int(stress.get("h6_confluence_total") or 0),
            "h6_confluence_neutralized": int(stress.get("h6_confluence_neutralized") or 0),
            "obv_divergence_cap": float(stress.get("obv_divergence_cap") or params.obv_divergence_cap),
            "mtf_confluence_block_enabled": bool(params.mtf_confluence_block_enabled),
            "buy_threshold": float(stress.get("buy_threshold") or params.buy_threshold),
            "total_oos_trades": int(stress.get("total_oos_trades") or 0),
        }
        stress_rows.append(row)
        print(
            f"  status={row['status']} base_oos={_fmt(base_oos)} "
            f"stress_oos={_fmt(stress_oos)} decay={_fmt(edge_decay)} "
            f"dd={_fmt(stress_dd)} overfit={_fmt(overfit)} robust={_fmt(robust)} "
            f"ctm={_fmt(row['counter_trend_multiplier'])}"
        )

    stress_fields = [
        "ticker",
        "status",
        "windows",
        "base_oos_mean_return",
        "stress_oos_mean_return",
        "edge_decay",
        "stress_oos_max_dd",
        "stress_is_mean_return",
        "has_overfitting_warning",
        "base_has_overfitting_warning",
        "robust",
        "buy_threshold",
        "total_oos_trades",
        "counter_trend_multiplier",
        "gates",
        "obv_trend_notnull",
        "h4_long_fired",
        "h4_short_fired",
        "h6_confluence_total",
        "h6_confluence_neutralized",
        "obv_divergence_cap",
        "mtf_confluence_block_enabled",
    ]
    write_csv(stress_rows, stress_path, stress_fields)

    robust_rows = [r for r in stress_rows if r.get("robust")]
    watchlist_fields = [
        "ticker",
        "stress_oos_mean_return",
        "stress_oos_max_dd",
        "base_oos_mean_return",
        "edge_decay",
        "has_overfitting_warning",
        "buy_threshold",
        "total_oos_trades",
        "windows",
        "counter_trend_multiplier",
    ]
    # Sort robust names by stress OOS descending for operator convenience.
    robust_sorted = sorted(
        robust_rows,
        key=lambda r: float(r["stress_oos_mean_return"] or -1e9),
        reverse=True,
    )
    write_csv(robust_sorted, watchlist_path, watchlist_fields)

    # Console tables
    print("=" * 110)
    print(
        f"{'Ticker':<12} {'BaseOOS%':>9} {'StressOOS%':>11} {'Decay':>8} "
        f"{'StressDD%':>10} {'Overfit':>8} {'Robust':>7} {'CTM':>6}"
    )
    print("-" * 110)
    for row in stress_rows:
        print(
            f"{row['ticker']!s:<12} {_fmt(row['base_oos_mean_return']):>9} "
            f"{_fmt(row['stress_oos_mean_return']):>11} {_fmt(row['edge_decay']):>8} "
            f"{_fmt(row['stress_oos_max_dd']):>10} {_fmt(row['has_overfitting_warning']):>8} "
            f"{_fmt(row['robust']):>7} {_fmt(row['counter_trend_multiplier']):>6}"
        )
    print("=" * 110)

    ok = [r for r in stress_rows if r.get("status") == "OK"]
    stress_oos_vals = [
        float(r["stress_oos_mean_return"])
        for r in ok
        if r.get("stress_oos_mean_return") is not None
    ]
    decays = [float(r["edge_decay"]) for r in ok if r.get("edge_decay") is not None]
    positive_stress = sum(1 for v in stress_oos_vals if v > 0)
    overfit_n = sum(1 for r in ok if r.get("has_overfitting_warning"))

    print("Stress universe summary (status=OK)")
    print(f"  tickers_ok              : {len(ok)}/{len(stress_rows)}")
    if stress_oos_vals:
        print(f"  median stress OOS %     : {statistics.median(stress_oos_vals):.2f}")
        print(f"  mean stress OOS %       : {statistics.mean(stress_oos_vals):.2f}")
        print(
            f"  positive stress OOS %   : {100.0 * positive_stress / len(ok):.1f}% "
            f"({positive_stress}/{len(ok)})"
        )
    if decays:
        print(f"  mean edge decay (pp)    : {statistics.mean(decays):.2f}")
        print(f"  median edge decay (pp)  : {statistics.median(decays):.2f}")
    print(f"  overfitting share       : {100.0 * overfit_n / max(len(ok), 1):.1f}% ({overfit_n}/{len(ok)})")
    print(
        f"  robust survivors        : {len(robust_sorted)} "
        f"(stress_oos>0, no overfit, dd>{args.max_dd})"
    )
    if robust_sorted:
        print(
            "  robust list             : "
            + ", ".join(
                f"{r['ticker']}({float(r['stress_oos_mean_return']):.1f}%)"
                for r in robust_sorted
            )
        )
    else:
        print("  robust list             : (empty)")

    print(f"Stress CSV   : {stress_path}")
    print(f"Watchlist CSV: {watchlist_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
