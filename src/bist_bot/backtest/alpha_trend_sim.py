"""Shared CAUSAL simulator for the Alpha Trend research stack.

Single source of truth for alpha-trend backtests (``scripts/fast_grid_alpha.py``,
``scripts/prototype_alpha_trend.py``, ``scripts/benchmark_alpha_stress.py``).
The exit engine is fully causal — no intrabar look-ahead:

- The trailing stop active during bar ``i`` is derived ONLY from data
  through bar ``i-1`` (close-peak and ATR of the previous bar). The
  ratchet computed at bar ``i``'s close becomes active for bar ``i+1`` —
  the same ordering as the live ``position_manager._update_stop_loss``
  ratchet. (Round-2 finding: deriving bar ``i``'s stop from bar ``i``'s
  own close and testing bar ``i``'s low against it inflated PF from a
  reported 1.428 to a true causal value of ~1.001.)
- The ENTRY bar's low IS tested against the initial stop (day-0 stop-out).
- Initial stop: ``max(entry - 1.5*ATR(signal bar), entry*(1 - max_stop_pct/100))``;
  minimum stop cushion 1.5% -> floor at ``entry*0.985`` (production parity).
- Entry executes at the NEXT bar's open after a signal close.
- Gap handling: exit fill at ``min(open, effective_stop)``.

Convention note: the close-peak is seeded at the ENTRY BAR'S OPEN (the
scripts lineage convention). The production ``Backtester`` seeds its
trail peak at the entry bar's close — a documented, intentional
difference between the two engines.

``scripts/benchmark_independent.py`` deliberately keeps its own
independent implementation and cross-checks this module (TEST 0).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

INIT_STOP_ATR_MULT = 1.5
MIN_STOP_CUSHION = 0.015
STOP_FLOOR_MULT = 0.985
VOLUME_SURGE_MULT = 1.4
BREAKOUT_BARS = 20
CLOSE_POS_MIN = 0.65
SIM_START_BAR = 60
MIN_COMMON_BARS = 70


@dataclass
class SimTrade:
    """One simulated alpha-trend trade (field-compatible with the scripts' legacy Trade)."""

    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    net_pnl_pct: float = 0.0
    holding_bars: int = 0


@dataclass
class StockData:
    """Precomputed per-ticker arrays aligned on the benchmark intersection."""

    ticker: str
    dates: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    sig: np.ndarray  # entry signal (bool), aligned to dates
    bull: np.ndarray  # benchmark bullish regime (bool), aligned to dates


def fetch_or_load(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    """Fetch one ticker's OHLCV (lowercase columns, >60 bars) or None."""
    from bist_bot.data.fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    try:
        df = fetcher.fetch_single(ticker, period=period, interval="1d")
        if df is not None and not df.empty and len(df) > 60:
            df.columns = [c.lower() for c in df.columns]
            return df
    except Exception:
        pass
    return None


def preload_all(
    tickers: list[str], period: str = "2y"
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Fetch XU100 (with market_bullish regime) + per-ticker history cache."""
    xu100 = fetch_or_load("XU100.IS", period=period)
    if xu100 is None:
        raise RuntimeError("XU100.IS fetch failed")
    xu100["sma50"] = xu100["close"].rolling(50).mean()
    xu100["sma20"] = xu100["close"].rolling(20).mean()
    xu100["market_bullish"] = (xu100["close"] > xu100["sma50"]) & (xu100["close"] > xu100["sma20"])

    cache: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch_or_load(t, period=period)
        if df is not None:
            cache[t] = df
    return xu100, cache


def prepare_stock(ticker: str, stock: pd.DataFrame, bench: pd.DataFrame) -> StockData:
    """Compute alpha-trend indicators for one ticker (benchmark-aligned)."""
    s = stock.copy()

    tr = pd.concat(
        [
            s["high"] - s["low"],
            (s["high"] - s["close"].shift(1)).abs(),
            (s["low"] - s["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(14).mean()

    vol_sma20 = s["volume"].rolling(20).mean()
    high_n = s["high"].rolling(BREAKOUT_BARS).max().shift(1)

    rs = s["close"] / bench["close"]
    rs_sma20 = rs.rolling(20).mean()
    rs_sma50 = rs.rolling(50).mean()
    rs_strong = (rs > rs_sma20) & (rs_sma20 > rs_sma50)

    rng = (s["high"] - s["low"]).replace(0, np.nan)
    close_pos = (s["close"] - s["low"]) / rng
    green = (s["close"] > s["open"]) & (close_pos >= CLOSE_POS_MIN)
    vol_surge = s["volume"] >= (VOLUME_SURGE_MULT * vol_sma20)
    breakout = s["close"] >= high_n

    bull = pd.Series(np.asarray(bench["market_bullish"], dtype=bool), index=s.index)
    sig = (bull & rs_strong & vol_surge & breakout & green).fillna(False).astype(bool)

    return StockData(
        ticker=ticker,
        dates=s.index,
        o=s["open"].to_numpy(dtype=float),
        h=s["high"].to_numpy(dtype=float),
        lo=s["low"].to_numpy(dtype=float),
        c=s["close"].to_numpy(dtype=float),
        atr=atr.to_numpy(dtype=float),
        sig=sig.to_numpy(dtype=bool),
        bull=np.asarray(bull, dtype=bool),
    )


def simulate_strategy(
    sd: StockData,
    trail_mult: float,
    max_stop_pct: float,
    cost_roundtrip_pct: float,
) -> list[SimTrade]:
    """Run the causal simulation on one prepared ticker."""
    trades: list[SimTrade] = []
    in_pos = False
    entry_p = stop_p = peak = 0.0
    entry_i = -1

    for i in range(SIM_START_BAR, len(sd.dates)):
        op, lo, cl = sd.o[i], sd.lo[i], sd.c[i]

        if in_pos:
            # Causal trailing: stop for bar i from data through bar i-1.
            eff = max(stop_p, peak - trail_mult * sd.atr[i - 1])
            if lo <= eff:
                exit_p = min(op, eff)
                gross = (exit_p - entry_p) / entry_p * 100.0
                trades.append(
                    SimTrade(
                        ticker=sd.ticker,
                        entry_date=sd.dates[entry_i],
                        entry_price=entry_p,
                        exit_date=sd.dates[i],
                        exit_price=exit_p,
                        exit_reason="TRAILING_STOP" if eff > stop_p else "INITIAL_STOP",
                        net_pnl_pct=gross - cost_roundtrip_pct,
                        holding_bars=i - entry_i,
                    )
                )
                in_pos = False
            elif cl > peak:
                # Ratchet computed at bar i's close -> active for bar i+1.
                peak = cl

        elif sd.sig[i - 1] and not np.isnan(sd.atr[i - 1]):
            entry_p = op
            stop_p = max(
                entry_p - INIT_STOP_ATR_MULT * sd.atr[i - 1],
                entry_p * (1.0 - max_stop_pct / 100.0),
            )
            if (entry_p - stop_p) / entry_p < MIN_STOP_CUSHION:
                stop_p = entry_p * STOP_FLOOR_MULT
            in_pos = True
            peak = entry_p
            entry_i = i
            # Day-0 stop check: the initial stop is known at entry time.
            if lo <= stop_p:
                gross = (stop_p - entry_p) / entry_p * 100.0
                trades.append(
                    SimTrade(
                        ticker=sd.ticker,
                        entry_date=sd.dates[entry_i],
                        entry_price=entry_p,
                        exit_date=sd.dates[i],
                        exit_price=stop_p,
                        exit_reason="INITIAL_STOP",
                        net_pnl_pct=gross - cost_roundtrip_pct,
                        holding_bars=0,
                    )
                )
                in_pos = False

    if in_pos:
        cl_last = sd.c[-1]
        gross = (cl_last - entry_p) / entry_p * 100.0
        trades.append(
            SimTrade(
                ticker=sd.ticker,
                entry_date=sd.dates[entry_i],
                entry_price=entry_p,
                exit_date=sd.dates[-1],
                exit_price=cl_last,
                exit_reason="FINAL_CLOSE",
                net_pnl_pct=gross - cost_roundtrip_pct,
                holding_bars=len(sd.dates) - 1 - entry_i,
            )
        )

    return trades


def run_trades(
    xu100: pd.DataFrame,
    cache: dict[str, pd.DataFrame],
    trail_mult: float,
    max_stop_pct: float,
    cost_roundtrip_pct: float = 0.35,
) -> list[SimTrade]:
    """Run the causal simulation over the whole ticker cache."""
    all_trades: list[SimTrade] = []
    for t, df in cache.items():
        common = df.index.intersection(xu100.index)
        if len(common) < MIN_COMMON_BARS:
            continue
        sd = prepare_stock(t, df.loc[common], xu100.loc[common])
        all_trades.extend(simulate_strategy(sd, trail_mult, max_stop_pct, cost_roundtrip_pct))
    return all_trades


def trade_stats(trades: list[SimTrade]) -> dict[str, float]:
    """Aggregate performance stats for a list of SimTrades."""
    n = len(trades)
    if n == 0:
        return {
            "n": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "avg_net_pp": 0,
            "avg_win_pp": 0,
            "avg_loss_pp": 0,
        }

    pnls = [t.net_pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.001

    return {
        "n": n,
        "win_rate": round(len(wins) / n * 100.0, 1),
        "profit_factor": round(gross_profit / gross_loss, 3),
        "avg_net_pp": round(sum(pnls) / n, 3),
        "avg_win_pp": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_pp": round(sum(losses) / len(losses), 2) if losses else 0.0,
    }


def evaluate(
    xu100: pd.DataFrame,
    cache: dict[str, pd.DataFrame],
    trail_mult: float,
    max_stop_pct: float,
    cost_roundtrip_pct: float = 0.35,
) -> dict[str, float]:
    """Aggregate causal-simulation stats over the whole ticker cache."""
    trades = run_trades(xu100, cache, trail_mult, max_stop_pct, cost_roundtrip_pct)
    return trade_stats(trades)
