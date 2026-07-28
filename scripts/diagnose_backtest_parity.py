"""Pre-refactor parity diagnostic: vectorized vs live scoring.

Read-only: does NOT modify engine.py. Builds a synthetic OHLCV with REAL
indicators, then for each bar compares:

  - vec_score  : the score column produced by Backtester._precalculate_signals
                 (the vectorized NumPy path used by _run_vectorized)
  - live_score : the score returned by calculate_score_and_reasons
                 (the single source of truth used by StrategyEngine.analyze)

Writes results/backtest_parity_gap.csv with columns:
  ticker, date, vec_score, live_score, delta

Console summary:
  - rows where |delta| > 1
  - maximum |delta|
  - whether a difference exists even in BASE scoring (H1/H3 disabled)
"""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bist_bot.backtest.engine import Backtester  # noqa: E402
from bist_bot.indicators import TechnicalIndicators  # noqa: E402
from bist_bot.strategy.engine_filters import calculate_score_and_reasons  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402
from bist_bot.strategy.regime import (  # noqa: E402
    check_momentum_confirmation,
)
from bist_bot.strategy.scoring import (  # noqa: E402
    score_momentum,
    score_structure,
    score_trend,
    score_volume,
)

TICKER = "TEST.IS"


class IdentityIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()


def build_synthetic_frame(periods: int = 260) -> pd.DataFrame:
    """Synthetic OHLCV with enough regime variety to exercise scoring."""
    rows: list[dict[str, float | str | datetime]] = []
    dates = pd.date_range(datetime(2023, 1, 1), periods=periods, freq="D")
    for idx, date in enumerate(dates):
        phase = idx % 44
        base = 100.0 + idx * 0.15 + math.sin(idx / 7) * 4.0
        if phase < 8:
            rsi = 22.0
            sma_cross = "GOLDEN_CROSS" if phase == 0 else "NONE"
            macd_cross = "BULLISH"
            bb_position = "BELOW_LOWER"
        elif 22 <= phase < 30:
            rsi = 80.0
            sma_cross = "DEATH_CROSS" if phase == 22 else "NONE"
            macd_cross = "BEARISH"
            bb_position = "ABOVE_UPPER"
        else:
            rsi = 50.0
            sma_cross = "NONE"
            macd_cross = "NONE"
            bb_position = "MIDDLE"
        rows.append(
            {
                "date": date,
                "open": base,
                "high": base + 3.0,
                "low": base - 3.0,
                "close": base + 0.8,
                "volume": 10_000,
                "rsi": rsi,
                "sma_cross": sma_cross,
                "macd_cross": macd_cross,
                "bb_position": bb_position,
            }
        )
    df = pd.DataFrame(rows).set_index("date")
    return df


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Run the real indicator pipeline so all columns scoring.py reads exist."""
    ind = TechnicalIndicators()
    enriched = ind.add_all(df.copy())
    # live path sets _prev_close_for_scoring on the last row; we set it for
    # every row so per-row live scoring matches what StrategyEngine would do.
    enriched["_prev_close_for_scoring"] = enriched["close"].shift(1)
    return enriched


def _vec_scores(df: pd.DataFrame) -> np.ndarray:
    """Return the raw (pre-shift) score array from the vectorized path.

    ``_precalculate_signals`` stores the raw per-bar score in ``_raw_score``
    before shifting ``score`` by 1 (signals are evaluated on the prior bar's
    close and executed on the current open). We compare ``_raw_score`` against
    the live per-row score.
    """
    backtester = Backtester(
        initial_capital=10_000,
        indicators=IdentityIndicators(),
    )
    pre = backtester._precalculate_signals(df.copy())
    return pre["_raw_score"].to_numpy(dtype=float)


def _live_scores(df: pd.DataFrame) -> list[float | None]:
    """Return per-row calculate_score_and_reasons result (H1/H3 ON)."""
    params = StrategyParams()

    # calculate_score_and_reasons expects trend_scorer(last, prev, df) and other scorers
    # / (last:) — i.e. params already bound, matching StrategyEngine._score_*.
    def momentum_scorer(last, prev):
        return score_momentum(params, last, prev)

    def trend_scorer(last, prev, df=None):
        return score_trend(params, last, prev, df)

    def volume_scorer(last, prev):
        return score_volume(params, last, prev)

    def structure_scorer(last):
        return score_structure(params, last)

    scores: list[float | None] = []
    for i in range(1, len(df)):
        last = df.iloc[i]
        prev = df.iloc[i - 1]
        result = calculate_score_and_reasons(
            params,
            TICKER,
            df.iloc[: i + 1],
            last=last,
            prev=prev,
            momentum_scorer=momentum_scorer,
            trend_scorer=trend_scorer,
            volume_scorer=volume_scorer,
            structure_scorer=structure_scorer,
            momentum_checker=check_momentum_confirmation,
            reject_logger=None,
        )
        if result is None:
            scores.append(None)
        else:
            scores.append(result[0])
    return scores


def _base_scores(df: pd.DataFrame) -> list[float]:
    """Per-row raw component sum WITHOUT sideways/momentum gates (H1/H3 OFF)."""
    params = StrategyParams()
    out: list[float] = [0.0]
    for i in range(1, len(df)):
        last = df.iloc[i]
        prev = df.iloc[i - 1]
        s1, _ = score_momentum(params, last, prev)
        s2, _ = score_trend(params, last, prev, df)
        s3, _ = score_volume(params, last, prev)
        s4, _ = score_structure(params, last)
        out.append(max(-100.0, min(100.0, s1 + s2 + s3 + s4)))
    return out


def main() -> int:
    df = build_synthetic_frame()
    enriched = _enrich(df)

    vec = _vec_scores(enriched)
    live = _live_scores(enriched)
    base = _base_scores(enriched)

    rows: list[dict[str, object]] = []
    for i in range(1, len(enriched)):
        v = float(vec[i])
        live_val = float(live[i - 1]) if live[i - 1] is not None else 0.0
        rows.append(
            {
                "ticker": TICKER,
                "date": str(enriched.index[i].date()),
                "vec_score": round(v, 6),
                "live_score": round(live_val, 6),
                "delta": round(v - live_val, 6),
                "base_score": round(base[i], 6),
                "base_vs_vec_delta": round(v - base[i], 6),
            }
        )

    out_df = pd.DataFrame(rows)
    out_path = ROOT_DIR / "results" / "backtest_parity_gap.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    deltas = out_df["delta"].abs()
    base_vs_vec = out_df["base_vs_vec_delta"].abs()
    print("=" * 60)
    print("BACKTEST PARITY (vectorized vs live scoring)")
    print("=" * 60)
    print(f"rows compared      : {len(out_df)}")
    print(f"rows |delta| > 1   : {int((deltas > 1).sum())}")
    print(f"rows |delta| > 0.01: {int((deltas > 0.01).sum())}")
    print(f"max |delta|        : {float(deltas.max()):.6f}")
    print(f"mean |delta|       : {float(deltas.mean()):.6f}")
    print()
    print("BASE scoring (H1/H3 disabled) vs vectorized:")
    print("  (rows where base != vec are rows where calculate_score_and_reasons")
    print("   returned None due to sideways/momentum gates -> score 0)")
    print(f"  rows |base_vs_vec| > 0.01 : {int((base_vs_vec > 0.01).sum())}")
    print(f"  max |base_vs_vec|         : {float(base_vs_vec.max()):.6f}")
    print()
    print(f"CSV written: {out_path}")

    # A few sample rows where the gap is largest
    if len(out_df):
        top = out_df.reindex(out_df["delta"].abs().sort_values(ascending=False).index).head(10)
        print("\nTop 10 gap rows:")
        print(top.to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
