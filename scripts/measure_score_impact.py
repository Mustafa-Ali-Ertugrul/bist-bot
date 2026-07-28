"""Backtest score impact measurement.

Synthesizes deterministic OHLCV data (seed-controlled) and runs the scoring
pipeline plus SELL stop/target generation. Produces a JSON metrics file
suitable for before/after diff comparison.

Usage:
    python scripts/measure_score_impact.py --output metrics.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bist_bot.indicators import TechnicalIndicators  # noqa: E402
from bist_bot.risk.manager import RiskManager  # noqa: E402
from bist_bot.strategy.engine_filters import classify_signal  # noqa: E402
from bist_bot.strategy.engine_meta import apply_buy_side_risk  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.regime import TrendBias  # noqa: E402
from bist_bot.strategy.scoring import (  # noqa: E402
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)
from bist_bot.strategy.signal_models import SignalType  # noqa: E402


def _safe_score_volume(params, last, prev):
    """score_volume signature differs across versions; tolerate both."""
    try:
        return score_volume(params, last, prev)
    except TypeError:
        return score_volume(params, last)


def _build_ohlcv(n_bars: int, regime: str, rng: np.random.Generator) -> pd.DataFrame:
    close = np.zeros(n_bars, dtype=float)
    close[0] = 100.0
    drift_map = {
        "uptrend": 0.0015,
        "downtrend": -0.0015,
        "sideways": 0.0,
        "volatile": 0.0,
        "breakout": 0.0,
    }
    vol_map = {
        "uptrend": 0.012,
        "downtrend": 0.012,
        "sideways": 0.008,
        "volatile": 0.04,
        "breakout": 0.018,
    }
    for i in range(1, n_bars):
        if regime == "breakout" and i > n_bars // 2:
            drift = 0.003
        else:
            drift = drift_map.get(regime, 0.0)
        vol = vol_map.get(regime, 0.01)
        ret = drift + vol * rng.standard_normal()
        close[i] = close[i - 1] * (1 + ret)
    high = close * (1 + np.abs(rng.standard_normal(n_bars)) * 0.005)
    low = close * (1 - np.abs(rng.standard_normal(n_bars)) * 0.005)
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(800_000, 1_500_000, n_bars).astype(float)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def generate_synthetic_data(n_bars: int, n_symbols: int, seed: int):
    regimes = ["uptrend", "downtrend", "sideways", "volatile", "breakout"]
    rng = np.random.default_rng(seed)
    symbols = []
    for i in range(n_symbols):
        regime = regimes[i % len(regimes)]
        df = _build_ohlcv(n_bars, regime, rng)
        symbols.append((f"SYN{i:02d}", df, regime))
    return symbols


def _stats(xs):
    if not xs:
        return {"count": 0}
    arr = np.asarray(xs, dtype=float)
    return {
        "count": int(arr.size),
        "mean": float(round(arr.mean(), 3)),
        "p50": float(round(np.percentile(arr, 50), 3)),
        "p90": float(round(np.percentile(arr, 90), 3)),
        "p99": float(round(np.percentile(arr, 99), 3)),
        "min": float(round(arr.min(), 3)),
        "max": float(round(arr.max(), 3)),
    }


def compute_metrics(symbols, *, n_bars: int, n_symbols: int, seed: int) -> dict:
    params = StrategyParams()
    ti = TechnicalIndicators()
    risk = RiskManager(capital=10000.0)

    counts = {n: 0 for n in (
        "STRONG_BUY", "BUY", "WEAK_BUY", "HOLD", "RADAR",
        "STRONG_SELL", "SELL", "WEAK_SELL",
    )}
    total_scores, mom_scores, trend_scores, vol_scores, struct_scores = [], [], [], [], []
    ema_initial_cross_count = 0

    sell_stops, sell_targets = [], []
    sell_stop_above_price = 0
    sell_target_below_price = 0

    for ticker, df, regime in symbols:  # noqa: B007
        if len(df) < 60:
            continue
        try:
            enriched = ti.add_all(df)
        except Exception:
            continue
        last = enriched.iloc[-1]
        prev = enriched.iloc[-2]

        s_m, _ = score_momentum(params, last, prev)
        s_t, r_t = score_trend(params, last, prev)
        s_v, _ = _safe_score_volume(params, last, prev)
        s_s, _ = score_structure(params, last)
        total = s_m + s_t + s_v + s_s

        signal_type, _ = classify_signal(params, total)
        counts[signal_type.name] = counts.get(signal_type.name, 0) + 1

        total_scores.append(total)
        mom_scores.append(s_m)
        trend_scores.append(s_t)
        vol_scores.append(s_v)
        struct_scores.append(s_s)

        if any(
            ("EMA" in r and ("kesti" in r or "yeni trend" in r or "kırılması" in r))
            for r in r_t
        ):
            ema_initial_cross_count += 1

        if signal_type.name in ("STRONG_SELL", "SELL", "WEAK_SELL"):
            try:
                risk_levels = risk.calculate(df)
                adjusted = apply_buy_side_risk(
                    risk,
                    None,
                    ticker,
                    df,
                    signal_type=SignalType.SELL,
                    enforce_sector_limit=False,
                    last=last,
                    score=total,
                    trend_bias=TrendBias.NEUTRAL,
                    risk_levels=risk_levels,
                )
                if adjusted is not None:
                    price = float(last["close"])
                    if adjusted.final_stop > 0:
                        sell_stops.append(adjusted.final_stop)
                        if adjusted.final_stop > price:
                            sell_stop_above_price += 1
                    if adjusted.final_target > 0:
                        sell_targets.append(adjusted.final_target)
                        if adjusted.final_target < price:
                            sell_target_below_price += 1
            except Exception:
                pass

    return {
        "config": {"n_bars": n_bars, "n_symbols": n_symbols, "seed": seed},
        "n_analyzed": len(total_scores),
        "signal_counts": counts,
        "scores": _stats(total_scores),
        "momentum": _stats(mom_scores),
        "trend": _stats(trend_scores),
        "volume": _stats(vol_scores),
        "structure": _stats(struct_scores),
        "ema_initial_cross_triggered_symbols": ema_initial_cross_count,
        "sell_stop_stats": _stats(sell_stops),
        "sell_target_stats": _stats(sell_targets),
        "sell_stop_above_price_count": sell_stop_above_price,
        "sell_target_below_price_count": sell_target_below_price,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n_symbols", type=int, default=30)
    parser.add_argument("--n_bars", type=int, default=200)
    args = parser.parse_args()

    symbols = generate_synthetic_data(args.n_bars, args.n_symbols, args.seed)
    metrics = compute_metrics(
        symbols, n_bars=args.n_bars, n_symbols=args.n_symbols, seed=args.seed
    )
    out = Path(args.output)
    out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Wrote {out}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
