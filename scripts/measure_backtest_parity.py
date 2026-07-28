"""Read-only parity measurement between backtest vectorized scoring and live calculate_score_and_reasons.

Run (from repo root):
    python scripts/measure_backtest_parity.py --limit 5

Writes results/backtest_parity_gap.csv with:
    ticker, date, vec_score, live_score, delta, live_no_h1h3_score, raw_delta

Console summary: rows with |delta| > 1, max |delta|, whether basic (H1/H3-free) scoring also differs.
"""

from __future__ import annotations

import argparse
import csv
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

warnings.filterwarnings("ignore")

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
DEFAULT_OUTPUT = REPO_ROOT / "results" / "backtest_parity_gap.csv"
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
        except Exception:
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


def measure_ticker(
    ticker: str,
    df: pd.DataFrame,
    params: StrategyParams,
    rows_out: list[dict[str, object]],
) -> tuple[int, int, float, float, float, float]:
    """Compare vectorized vs live scores for every row in df.

    Returns (n_rows, n_diff_gt1, max_abs_delta, max_raw_delta,
             max_abs_delta_no_h1h3, n_diff_gt1_no_h1h3).
    """
    enriched = TechnicalIndicators.add_all(df)
    enriched = enriched.dropna(subset=["rsi", f"sma_{settings.SMA_SLOW}"])

    # Build a Backtester just to reuse _precalculate_signals (vectorized scoring).
    from bist_bot.backtest.engine import Backtester

    bt = Backtester(
        initial_capital=100_000.0,
        strategy_params=params,
    )
    vec_df = bt._precalculate_signals(enriched)

    n_rows = 0
    n_diff_gt1 = 0
    max_abs_delta = 0.0
    max_abs_delta_no_h1h3 = 0.0
    n_diff_gt1_no_h1h3 = 0

    # Params with H1/H3 disabled for "basic" comparison
    params_basic = params.__class__(
        **{**params.__dict__, "counter_trend_multiplier": 1.0, "chase_block_enabled": False}
    )

    for i in range(50, len(enriched)):
        last = enriched.iloc[i]
        prev = enriched.iloc[i - 1]
        df_so_far = enriched.iloc[: i + 1]

        vec_score = float(vec_df.iloc[i]["score"])

        # Live score WITH H1/H3
        res_live = calculate_score_and_reasons(
            params,
            ticker,
            df_so_far,
            last=last,
            prev=prev,
            momentum_scorer=lambda lst, pr, _p=params: score_momentum(_p, lst, pr),
            trend_scorer=lambda lst, pr, _p=params: score_trend(_p, lst, pr),
            volume_scorer=lambda lst, pr, _p=params: score_volume(_p, lst, pr),
            structure_scorer=lambda lst, _p=params: score_structure(_p, lst),
            momentum_checker=check_momentum_confirmation,
        )
        live_score = float(res_live[0]) if res_live is not None else 0.0

        # Live score WITHOUT H1/H3 (basic)
        res_basic = calculate_score_and_reasons(
            params_basic,
            ticker,
            df_so_far,
            last=last,
            prev=prev,
            momentum_scorer=lambda lst, pr, _p=params_basic: score_momentum(_p, lst, pr),
            trend_scorer=lambda lst, pr, _p=params_basic: score_trend(_p, lst, pr),
            volume_scorer=lambda lst, pr, _p=params_basic: score_volume(_p, lst, pr),
            structure_scorer=lambda lst, _p=params_basic: score_structure(_p, lst),
            momentum_checker=check_momentum_confirmation,
        )
        basic_score = float(res_basic[0]) if res_basic is not None else 0.0

        delta = live_score - vec_score
        raw_delta = basic_score - vec_score

        n_rows += 1
        if abs(delta) > 1.0:
            n_diff_gt1 += 1
        if abs(raw_delta) > 1.0:
            n_diff_gt1_no_h1h3 += 1
        max_abs_delta = max(max_abs_delta, abs(delta))
        max_abs_delta_no_h1h3 = max(max_abs_delta_no_h1h3, abs(raw_delta))

        rows_out.append(
            {
                "ticker": ticker,
                "date": str(last.name),
                "vec_score": round(vec_score, 4),
                "live_score": round(live_score, 4),
                "delta": round(delta, 4),
                "live_no_h1h3_score": round(basic_score, 4),
                "raw_delta": round(raw_delta, 4),
            }
        )

    return n_rows, n_diff_gt1, max_abs_delta, max_abs_delta_no_h1h3, n_diff_gt1_no_h1h3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest vs live scoring parity measurement")
    parser.add_argument("--limit", type=int, default=0, help="Only first N tickers (0 = all)")
    parser.add_argument("--period", type=str, default="3y")
    parser.add_argument("--cache-dir", type=str, default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT))
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args(argv)

    tickers = list(BIST30_TICKERS)
    if args.limit and args.limit > 0:
        tickers = tickers[: args.limit]

    params = StrategyParams.conservative()
    params.counter_trend_multiplier = 0.0
    cache_dir = Path(args.cache_dir)
    output_path = Path(args.output)

    print("Backtest parity measurement (conservative, ctm=0.0)")
    print(f"  tickers={len(tickers)} period={args.period}")
    print("=" * 100)

    rows: list[dict[str, object]] = []
    total_rows = 0
    total_diff_gt1 = 0
    max_abs_delta_global = 0.0
    max_abs_delta_no_h1h3_global = 0.0
    total_diff_gt1_no_h1h3 = 0

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
            df = _load_csv_fallback(cache_dir, ticker, args.period)
        if df is None or len(df) < 50:
            print("  skip: insufficient data")
            continue

        n, d, m, m_no, d_no = measure_ticker(ticker, df, params, rows)
        total_rows += n
        total_diff_gt1 += d
        max_abs_delta_global = max(max_abs_delta_global, m)
        max_abs_delta_no_h1h3_global = max(max_abs_delta_no_h1h3_global, m_no)
        total_diff_gt1_no_h1h3 += d_no
        print(
            f"  rows={n} |delta|>1={d} max|delta|={m:.2f} | basic |delta|>1={d_no} max_basic|delta|={m_no:.2f}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "date",
        "vec_score",
        "live_score",
        "delta",
        "live_no_h1h3_score",
        "raw_delta",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})

    print("=" * 100)
    print("PARITY SUMMARY")
    print("-" * 100)
    print(f"Total rows compared            : {total_rows}")
    print(f"Rows with |delta| > 1 (live)   : {total_diff_gt1}")
    print(f"Max |delta| (live vs vec)      : {max_abs_delta_global:.4f}")
    print(f"Rows with |delta| > 1 (basic)  : {total_diff_gt1_no_h1h3}")
    print(f"Max |delta| (basic vs vec)     : {max_abs_delta_no_h1h3_global:.4f}")
    print("-" * 100)
    if total_diff_gt1_no_h1h3 > 0:
        print(
            "BASIC (H1/H3-free) scoring ALSO differs -> iki beyin zaten farkliydi (skor temelde ayrismali)."
        )
    else:
        print("BASIC (H1/H3-free) scoring matches -> fark H1/H3 ek fazlasindan kaynaklaniyor.")
    print(f"CSV written: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
