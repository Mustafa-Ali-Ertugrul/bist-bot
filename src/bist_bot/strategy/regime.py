"""Market regime and multi-timeframe helpers for strategy scoring."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from enum import Enum
from pathlib import Path

import pandas as pd

from bist_bot.config.settings import settings
from bist_bot.strategy.signal_models import SignalType


class MarketRegime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class TrendBias(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


def detect_regime(df: pd.DataFrame, lookback: int = 20) -> MarketRegime:
    """Infer the current market regime from trend indicators."""
    _ = lookback
    if df is None or len(df) < 50:
        return MarketRegime.UNKNOWN

    last = df.iloc[-1]
    adx = last.get("adx", 0)
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)
    close = float(last["close"])

    trend_adx = 20
    weak_adx = 15
    di_ratio = 1.25

    sma_20 = float(df["close"].tail(20).mean())
    momentum = (close - sma_20) / sma_20 * 100

    if adx >= trend_adx:
        if plus_di > minus_di * di_ratio:
            return MarketRegime.BULL
        if minus_di > plus_di * di_ratio:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    if adx >= weak_adx:
        if momentum > 3 and plus_di > minus_di:
            return MarketRegime.BULL
        if momentum < -3 and minus_di > plus_di:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    return MarketRegime.SIDEWAYS


def get_trend_bias(indicators, df: pd.DataFrame) -> TrendBias:
    """Determine higher-timeframe directional bias for MTF confluence.

    H6: When SMA20 slope and EMA200 slope point in opposite directions, the
    HTF bias is internally contradictory → return NEUTRAL (whipsaw guard).
    Uses H2's slope_lookback from settings (default 40).
    """
    if df is None or len(df) < 30:
        return TrendBias.NEUTRAL

    enriched = indicators.add_all(df.copy())
    regime = detect_regime(enriched)
    last = enriched.iloc[-1]
    close = float(last["close"])
    ema_long = last.get(f"ema_{settings.EMA_LONG}")
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)

    # H6: SMA20/EMA200 slope contradiction → NEUTRAL (no new params)
    mtf_block_enabled = getattr(settings, "MTF_CONFLUENCE_BLOCK_ENABLED", True)
    slope_lookback = getattr(settings, "SLOPE_LOOKBACK", 40)
    if (
        mtf_block_enabled
        and "sma_20" in enriched.columns
        and f"ema_{settings.EMA_LONG}" in enriched.columns
        and len(enriched) >= slope_lookback + 1
    ):
        sma_20_series = enriched["sma_20"]
        ema_long_series = enriched[f"ema_{settings.EMA_LONG}"]
        sma_20_slope = float(sma_20_series.iloc[-1]) - float(
            sma_20_series.iloc[-1 - slope_lookback]
        )
        ema_200_slope = float(ema_long_series.iloc[-1]) - float(
            ema_long_series.iloc[-1 - slope_lookback]
        )
        sma_20_dir = 1 if sma_20_slope > 0 else (-1 if sma_20_slope < 0 else 0)
        ema_200_dir = 1 if ema_200_slope > 0 else (-1 if ema_200_slope < 0 else 0)
        if sma_20_dir != 0 and ema_200_dir != 0 and sma_20_dir != ema_200_dir:
            return TrendBias.NEUTRAL

    if (
        regime == MarketRegime.BULL
        and pd.notna(ema_long)
        and close >= float(ema_long)
        and plus_di >= minus_di
    ):
        return TrendBias.LONG
    if (
        regime == MarketRegime.BEAR
        and pd.notna(ema_long)
        and close <= float(ema_long)
        and minus_di >= plus_di
    ):
        return TrendBias.SHORT
    return TrendBias.NEUTRAL


def apply_confluence(signal_type: SignalType, trend_bias: TrendBias, reasons: list[str]) -> bool:
    """Validate multi-timeframe confluence for directional signals."""
    long_signals = {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WEAK_BUY}
    short_signals = {SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL}

    if signal_type in long_signals:
        if trend_bias == TrendBias.LONG:
            reasons.append("MTF confluence: günlük trend LONG, 15dk tetik destekliyor")
            return True
        if trend_bias == TrendBias.NEUTRAL:
            reasons.append("MTF confluence zayıf: üst zaman dilimi nötr (RADAR adayı)")
        else:
            reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
        return False

    if signal_type in short_signals:
        if trend_bias == TrendBias.SHORT:
            reasons.append("MTF confluence: günlük trend SHORT, 15dk tetik destekliyor")
            return True
        if trend_bias == TrendBias.NEUTRAL:
            reasons.append("MTF confluence zayıf: üst zaman dilimi nötr (RADAR adayı)")
        else:
            reasons.append(f"MTF confluence başarısız: üst zaman dilimi {trend_bias.value}")
        return False

    return True


def check_regime_persistence(
    df: pd.DataFrame, target_regime: MarketRegime, min_bars: int = 2
) -> bool:
    """Check whether a target regime persisted for the latest bars."""
    if len(df) < min_bars + 1:
        return False
    for i in range(len(df) - min_bars, len(df)):
        sub = df.iloc[: i + 1]
        if detect_regime(sub) != target_regime:
            return False
    return True


def check_momentum_confirmation(df: pd.DataFrame, threshold: float = 4.0) -> bool:
    """Validate momentum when the primary trend signal is weak."""
    if len(df) < 20:
        return True
    last = df.iloc[-1]
    adx = last.get("adx", 0)
    plus_di = last.get("plus_di", 0)
    minus_di = last.get("minus_di", 0)
    if adx >= 20:
        return True
    if abs(plus_di - minus_di) >= 5:
        return True
    sma_20 = float(df["close"].tail(20).mean())
    momentum = (float(last["close"]) - sma_20) / sma_20 * 100
    return abs(momentum) >= threshold


# ---------------------------------------------------------------------------
# Macro-level regime detection (Item 1)
# ---------------------------------------------------------------------------

MACRO_BENCHMARK_TICKERS = ("THYAO.IS", "GARAN.IS", "AKBNK.IS")
"""Tickers used as a lightweight proxy for the broader market regime."""

# Single constant source: a benchmark must have at least this many rows of
# history (as-of each evaluated date) before its regime vote counts. Mirrors
# the ``len(df) < 50`` guard in the live ``detect_regime`` path.
MACRO_REGIME_MIN_BARS = 50


def _normalize_benchmark_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw benchmark OHLCV frame for regime-series construction.

    Same index rules the backtester alignment uses downstream: tz-aware
    indices are converted to UTC then made tz-naive; index is sorted;
    duplicate dates collapse with ``keep="last"``; rows with NaN close are
    dropped.
    """
    out = df.copy()
    out.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in out.columns]
    for alias in ("adj close", "adj_close"):
        if alias in out.columns and "close" not in out.columns:
            out = out.rename(columns={alias: "close"})
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out.index = idx
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.dropna(subset=["close"])


def benchmark_regime_series(enriched: pd.DataFrame) -> pd.Series:
    """Vectorized per-date regime for one *enriched* benchmark frame.

    Row ``t`` reproduces ``detect_regime(enriched.iloc[:t+1])`` exactly
    (detect_regime only reads the last row's adx/plus_di/minus_di/close plus
    a 20-close trailing mean, and all indicators are causal). Rows before
    ``MACRO_REGIME_MIN_BARS`` get ``MarketRegime.UNKNOWN`` instead of a vote,
    mirroring the live ``len(df) < 50`` skip.
    """
    trend_adx = 20
    weak_adx = 15
    di_ratio = 1.25

    close = enriched["close"].astype(float)
    adx = (
        enriched["adx"].astype(float)
        if "adx" in enriched.columns
        else pd.Series(0.0, index=enriched.index)
    )
    plus_di = (
        enriched["plus_di"].astype(float)
        if "plus_di" in enriched.columns
        else pd.Series(0.0, index=enriched.index)
    )
    minus_di = (
        enriched["minus_di"].astype(float)
        if "minus_di" in enriched.columns
        else pd.Series(0.0, index=enriched.index)
    )
    sma_20 = close.rolling(20, min_periods=1).mean()
    momentum = (close - sma_20) / sma_20 * 100

    strong = adx >= trend_adx
    weak = (~strong) & (adx >= weak_adx)
    bull = (strong & (plus_di > minus_di * di_ratio)) | (
        weak & (momentum > 3) & (plus_di > minus_di)
    )
    bear = (strong & (minus_di > plus_di * di_ratio)) | (
        weak & (momentum < -3) & (minus_di > plus_di)
    )

    out = pd.Series(MarketRegime.SIDEWAYS, index=enriched.index, dtype=object)
    out[bull] = MarketRegime.BULL
    out[bear] = MarketRegime.BEAR
    if len(out) > 0:
        out.iloc[: max(0, min(len(out), MACRO_REGIME_MIN_BARS) - 1)] = MarketRegime.UNKNOWN
    return out


def build_macro_regime_series(
    benchmark_frames: Mapping[str, pd.DataFrame],
    *,
    indicators=None,
) -> pd.Series:
    """Build one shared daily macro-regime series from benchmark OHLCV frames.

    All three ``MACRO_BENCHMARK_TICKERS`` must be present with at least
    ``MACRO_REGIME_MIN_BARS`` rows each (post clean-up), else ``ValueError``.
    Each benchmark is enriched once over its full history; the per-date regime
    only depends on rows ``<= t`` (guaranteed by ``benchmark_regime_series``
    and covered by a brute-force causality test). Per-date aggregation uses
    ``aggregate_macro_regime`` — the exact rule the live gate applies — with
    each benchmark voting from its own as-of history (a benchmark votes only
    once it has ``MACRO_REGIME_MIN_BARS`` rows as-of that date).

    Returns a series indexed by the union of the three (normalized,
    tz-naive, sorted) benchmark date indices, values of type
    ``MarketRegime``.
    """
    missing = [t for t in MACRO_BENCHMARK_TICKERS if benchmark_frames.get(t) is None]
    if missing:
        raise ValueError(f"macro regime: missing benchmark data for {missing}")

    if indicators is None:
        from bist_bot.indicators import TechnicalIndicators

        indicators = TechnicalIndicators()

    per_benchmark: dict[str, pd.Series] = {}
    for ticker in MACRO_BENCHMARK_TICKERS:
        frame = _normalize_benchmark_frame(benchmark_frames[ticker])
        if len(frame) < MACRO_REGIME_MIN_BARS:
            raise ValueError(
                f"macro regime: benchmark {ticker} has {len(frame)} rows "
                f"(< {MACRO_REGIME_MIN_BARS}) after clean-up"
            )
        enriched = indicators.add_all(frame.copy())
        # Valid votes only from the row where the benchmark first reaches
        # MACRO_REGIME_MIN_BARS rows; earlier rows carry UNKNOWN but the
        # live gate skips such benchmarks, so we model "no vote" as NaN.
        votes = benchmark_regime_series(enriched)
        voteable = pd.Series(True, index=votes.index, dtype=bool)
        voteable.iloc[: MACRO_REGIME_MIN_BARS - 1] = False
        aligned_votes = votes.where(voteable)
        per_benchmark[ticker] = aligned_votes

    union_index: pd.DatetimeIndex | None = None
    for series in per_benchmark.values():
        union_index = series.index if union_index is None else union_index.union(series.index)
    assert union_index is not None

    aligned = {t: s.reindex(union_index, method="ffill") for t, s in per_benchmark.items()}
    regimes: list[MarketRegime] = []
    for date in union_index:
        votes = [
            series.loc[date]
            for series in aligned.values()
            if pd.notna(series.loc[date]) and isinstance(series.loc[date], MarketRegime)
        ]
        regimes.append(aggregate_macro_regime(votes))
    return pd.Series(regimes, index=union_index, dtype=object, name="macro_regime")


def load_macro_regime_series(
    cache_dir: str | Path,
    *,
    period: str = "3y",
    indicators=None,
) -> pd.Series:
    """Load benchmark OHLCV from the local parquet/CSV cache and build the
    shared macro regime series.

    Cache-only: never hits the network. Raises ``ValueError`` when any
    benchmark cache is missing, unreadable, or shorter than
    ``MACRO_REGIME_MIN_BARS`` rows. Shared by
    ``scripts/run_walk_forward_bist30.py`` and
    ``scripts/evaluate_july_2026_predictions.py``.
    """
    cache_dir = Path(cache_dir)
    frames: dict[str, pd.DataFrame] = {}
    for ticker in MACRO_BENCHMARK_TICKERS:
        safe = ticker.replace(".", "_").replace("/", "_")
        parquet_path = cache_dir / f"{safe}_{period}.parquet"
        csv_path = cache_dir / f"{safe}_{period}.csv"
        frame: pd.DataFrame | None = None
        if parquet_path.exists():
            try:
                frame = pd.read_parquet(parquet_path)
            except Exception as exc:
                raise ValueError(
                    f"macro regime: failed reading benchmark cache {parquet_path}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        elif csv_path.exists():
            try:
                frame = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            except Exception as exc:
                raise ValueError(
                    f"macro regime: failed reading benchmark cache {csv_path}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        if frame is None:
            raise ValueError(
                f"macro regime: benchmark cache missing for {ticker} "
                f"(looked for {parquet_path.name} / {csv_path.name} in {cache_dir})"
            )
        frames[ticker] = frame
    return build_macro_regime_series(frames, indicators=indicators)


def aggregate_macro_regime(regime_votes: list[MarketRegime]) -> MarketRegime:
    """Combine per-benchmark regime votes into one macro regime.

    Single source of truth for the macro aggregation rule, shared by the
    live gate (``detect_macro_regime``) and the backtest regime series
    (``build_macro_regime_series``). Rule: fewer than two votes → the single
    vote (or UNKNOWN); otherwise the *mode* of the votes with a
    deterministic tie-break: BULL > SIDEWAYS > BEAR > UNKNOWN.
    """
    if len(regime_votes) < 2:
        # Not enough data — fall back to the single available reading.
        return regime_votes[0] if regime_votes else MarketRegime.UNKNOWN

    counts = Counter(regime_votes)
    # Deterministic tie-break order: BULL > SIDEWAYS > BEAR > UNKNOWN.
    # Invert so higher-priority regimes get a larger sort key.
    tie_break_scores = {
        MarketRegime.BULL: 4,
        MarketRegime.SIDEWAYS: 3,
        MarketRegime.BEAR: 2,
        MarketRegime.UNKNOWN: 1,
    }
    best = max(counts, key=lambda r: (counts[r], tie_break_scores.get(r, 0)))
    return best


def detect_macro_regime(dfs: dict[str, pd.DataFrame]) -> MarketRegime:
    """Aggregate per-ticker regime into a single macro view.

    Returns ``MarketRegime.UNKNOWN`` when fewer than two benchmarks are
    available. The final decision is the *mode* of individual regimes, with
    a simple tie-break: BULL > SIDEWAYS > BEAR > UNKNOWN.
    """
    if not dfs:
        return MarketRegime.UNKNOWN

    regime_votes: list[MarketRegime] = []
    for _ticker, df in dfs.items():
        if df is None or len(df) < MACRO_REGIME_MIN_BARS:
            continue
        regime_votes.append(detect_regime(df))

    return aggregate_macro_regime(regime_votes)


def is_macro_bullish(dfs: dict[str, pd.DataFrame]) -> bool:
    """Return True when the macro regime is BULL or BEAR is absent."""
    regime = detect_macro_regime(dfs)
    return regime == MarketRegime.BULL


def is_macro_bearish(dfs: dict[str, pd.DataFrame]) -> bool:
    """Return True when the macro regime is BEAR."""
    return detect_macro_regime(dfs) == MarketRegime.BEAR
