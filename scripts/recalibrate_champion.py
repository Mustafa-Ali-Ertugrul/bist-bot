"""Champion recalibration harness — v2 toparlama planı adım 4.

İki mod:
  diagnose : mevcut champion konfigürasyonunun purge/embargo'lu, gerçekçi
             maliyetli OOS karnesi (optimize yok — gerçeği ölçer).
  search   : champion bandı sabit (28-33), geri kalan eşikler havuzlanmış-OOS
             beklentiyle aranır (purge'lu train, cost-aware fitness).

Kullanım (repo kökünden):
    python scripts/recalibrate_champion.py --mode diagnose
    python scripts/recalibrate_champion.py --mode search --iters 8

Notlar:
- Plain Backtester vektörel yolu + champion eşikleri + pv-gate birebir çalışır;
  canlıdaki 33-cap bandı BandedBacktester ile aynen uygulanır.
- Maliyet: realistic_cost_model (komisyon 15bps, spread 20bps, slip 30bps).
- Train penceresi 63 bar (gösterge ısınması ~50 bar istediği için 2 ay yetmez;
  v2'deki "2 ay" hedefi bu yüzden 3 ay olarak uygulandı — raporda açık yazılır).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bist_bot.backtest.engine import Backtester
from bist_bot.backtest.realistic_costs import realistic_cost_model
from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.strategy.params import StrategyParams

REPO_ROOT = Path(__file__).resolve().parents[1]
_TARGET_RR_OVERRIDE: float | None = None
_STOP_CAP_ATR: float | None = None
_STOP_CAP_PCT: float | None = None
_TIME_STOP_BARS: int | None = None
_MAX_STOP_PCT: float | None = None
_TARGET_ATR_MULT: float | None = None
_TRAILING_MULT: float | None = None
_PARITY_STOP: bool = False
_MACRO_MODE: str = "off"
_MACRO_SERIES: Any | None = None
_GAP_ENTRY_PCT: float | None = None
_GAP_ENTRY_ATR: float | None = None

# Pilot evren: en likit 10 (fetch + koşu süresi pilot ölçeğinde tutulur).
PILOT_TICKERS = [
    "THYAO.IS",
    "ASELS.IS",
    "GARAN.IS",
    "AKBNK.IS",
    "EREGL.IS",
    "TUPRS.IS",
    "BIMAS.IS",
    "KCHOL.IS",
    "SAHOL.IS",
    "ISCTR.IS",
]

TRAIN_DAYS = 63  # ~3 ay (gösterge ısınması nedeniyle 2 ay yetersiz)
TEST_DAYS = 21  # ~1 ay
STEP_DAYS = 21
PURGE_BARS = 10
EMBARGO_BARS = 5
# Gösterge ısınması (~50 bar) pencereyi yemesin diye train/test çerçeveleri
# geriye doğru uzatılır; kararlar ve OOS sayımı yine nominal sınırlarla yapılır.
WARMUP_BARS = 60
# Pozisyon çözümlemesi: giriş kapısı test son günü kapanır, ama açık pozisyonun
# hedef/stop'a yürümesi için çerçeve ileriye uzatılır (yoksa FINAL_CLOSE
# artefaktı gerçek zararmış gibi sayılır).
EXIT_EXTENSION_BARS = 28


class BandedBacktester(Backtester):
    """Champion 28-33 bandını vektörel yola uygular (canlı engine_filters §160)."""

    def _precalculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = super()._precalculate_signals(df)
        cap = float(self.strategy_params.max_actionable_score)
        floor = float(self.strategy_params.buy_threshold)
        mask = (df["score"] >= floor) & (df["score"] <= cap)
        if _MAX_STOP_PCT is not None:
            # Giriş filtresi: stopu %X'ten uzak kurulumları alma (hedefe
            # dokunulmaz — cap'ten farkı: geniş kurulum bozulmaz, atlanır).
            stop_dist = (df["close"] - df["calculated_stop"]) / df["close"] * 100.0
            mask = mask & (stop_dist <= _MAX_STOP_PCT)
        # Açılış boşluğu filtresi: t-1 close → t open arası boşluk;
        # fill=open olduğundan boşluksuz açılışta girme.
        if _GAP_ENTRY_PCT is not None or _GAP_ENTRY_ATR is not None:
            bad = gap_entry_filter_mask(df, gap_pct=_GAP_ENTRY_PCT, gap_atr=_GAP_ENTRY_ATR)
            mask = mask & ~bad
        df["enter_signal"] = (df["enter_signal"] & mask).astype(bool)
        return df


def gap_entry_filter_mask(
    df: pd.DataFrame,
    *,
    gap_pct: float | None = None,
    gap_atr: float | None = None,
) -> pd.Series:
    """Aşağı açılış boşluğu giriş filtresi (True = bu bar girişi ATLA).

    Karar t-1 close'da verilir, fill t open'ında olur; boşluk =
    (open[t] - close[t-1]) / close[t-1]. Yalnız aşağı boşluklar (long-only)
    süzülür; ATR kuralı ATR[t-1] kullanır (look-ahead yok). İlk bar NaN →
    False (giriş korunur). İki flag birlikte verilirse UNION.
    """
    prev_close = df["close"].shift(1)
    gap_pct_series = (df["open"] - prev_close) / prev_close * 100.0
    bad = pd.Series(False, index=df.index, dtype=bool)
    if gap_pct is not None:
        bad = bad | (gap_pct_series <= -gap_pct)
    if gap_atr is not None:
        if "atr" not in df.columns:
            raise KeyError("--gap-entry-atr requires 'atr' column (frame not indicator-enriched)")
        bad = bad | (
            (gap_pct_series < 0) & ((prev_close - df["open"]) > gap_atr * df["atr"].shift(1))
        )
    return bad


def _target_rr() -> float:
    if _TARGET_RR_OVERRIDE is not None:
        return _TARGET_RR_OVERRIDE
    try:
        return float(getattr(settings, "FALLBACK_TARGET_RR", 0.5) or 0.5)
    except (TypeError, ValueError):
        return 0.5


def make_factory(params: StrategyParams):
    target_rr = _target_rr()
    time_stop = _TIME_STOP_BARS
    target_atr_mult = _TARGET_ATR_MULT
    trailing_mult = _TRAILING_MULT
    macro_mode = _MACRO_MODE
    macro_series = _MACRO_SERIES

    def factory(
        *,
        initial_capital: float,
        cost_model: Any | None = None,
        commission_buy_pct: float | None = None,
        commission_sell_pct: float | None = None,
        slippage_pct: float | None = None,
        strategy_params: Any | None = None,
    ) -> BandedBacktester:
        _ = (cost_model, commission_buy_pct, commission_sell_pct, slippage_pct)
        return BandedBacktester(
            initial_capital=initial_capital,
            cost_model=realistic_cost_model(),
            target_rr=target_rr,
            strategy_params=strategy_params if strategy_params is not None else params,
            max_hold_bars=time_stop,
            target_atr_mult=target_atr_mult,
            trailing_atr_mult=trailing_mult,
            macro_regime_series=macro_series,
            macro_regime_mode=macro_mode,
        )

    return factory


def fetch_frames(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    fetcher = BISTDataFetcher()
    frames: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            df = fetcher.fetch_single(ticker, period=period, interval="1d")
        except Exception as exc:
            print(f"  [skip] fetch failed for {ticker}: {exc}", file=sys.stderr)
            continue
        if df is None or df.empty:
            print(f"  [skip] no bars for {ticker}", file=sys.stderr)
            continue
        frames[ticker] = df.sort_index()
    print(f"Bars loaded for {len(frames)}/{len(tickers)} tickers")
    return frames


def stop_cap_config() -> dict[str, Any]:
    return {
        "stop_cap_atr": _STOP_CAP_ATR,
        "stop_cap_pct": _STOP_CAP_PCT,
        "time_stop_bars": _TIME_STOP_BARS,
        "max_stop_pct": _MAX_STOP_PCT,
        "target_atr_mult": _TARGET_ATR_MULT,
        "trailing_mult": _TRAILING_MULT,
        "parity_stop": _PARITY_STOP,
        "macro_mode": _MACRO_MODE,
        "gap_entry_pct": _GAP_ENTRY_PCT,
        "gap_entry_atr": _GAP_ENTRY_ATR,
    }


def normalize_daily_index(df: pd.DataFrame) -> pd.DataFrame:
    """Motorun makro kapı şartı: tz-naive + normalize günlük indeks."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    idx = idx.normalize()
    out = df.copy()
    out.index = idx
    out = out.sort_index()
    return out[~out.index.duplicated(keep="last")]


def build_macro_series(frames: dict[str, pd.DataFrame]) -> Any:
    """Deney D ile aynı kapı: build_macro_regime_series (canlı parity)."""
    from bist_bot.strategy.regime import MACRO_BENCHMARK_TICKERS, build_macro_regime_series

    missing = [t for t in MACRO_BENCHMARK_TICKERS if t not in frames]
    if missing:
        raise SystemExit(
            f"--macro-mode için benchmark verisi yok: {missing} (universe bu tickerları içermeli)"
        )
    return build_macro_regime_series({t: frames[t] for t in MACRO_BENCHMARK_TICKERS})


# Canlı stop-seçim paritesi (Adım 1): risk/stops.py fonksiyonları birebir.
_PARITY_MIN_HISTORY = 50


def _parity_select_stop(price: float, levels: Any) -> float:
    """determine_final_levels'ın YALNIZCA stop-seçim kısmı (hedef/H8 yok)."""
    all_stops = {
        "ATR": levels.stop_atr,
        "Destek": levels.stop_support,
        "Fibonacci": levels.stop_fibonacci,
        "Yüzdelik": levels.stop_percent,
        "Swing": levels.stop_swing,
    }
    valid = {k: v for k, v in all_stops.items() if 0 < v < price}
    reasonable = {k: v for k, v in valid.items() if 0.01 < (price - v) / price < 0.10}
    if reasonable:
        final = max(reasonable.values())
    elif valid:
        final = max(valid.values())
    else:
        final = levels.stop_percent
    min_stop_pct = float(getattr(settings, "MIN_STOP_LOSS_PCT", 1.5))
    min_stop_price = price * (1 - min_stop_pct / 100.0)
    if 0 < final < price and final > min_stop_price:
        final = min_stop_price
    return float(final)


def parity_stop_series(df: pd.DataFrame) -> pd.Series:
    """Bar-bar canlı stop: risk/stops.py calc_* fonksiyonları + seçim.

    Sızıntı yok: bar t'nin stopu yalnızca df[:t+1] geçmişinden hesaplanır;
    motorun mevcut shift(1)'i giriş barına t-1 stopunu taşır (canlı akış).
    """
    from bist_bot.risk.models import RiskLevels
    from bist_bot.risk.stops import (
        calc_fibonacci,
        calc_fixed_percent,
        calc_support_resistance,
        calc_swing_levels,
    )

    closes = df["close"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float) if "atr" in df.columns else None
    out = np.full(len(df), np.nan)
    for t in range(_PARITY_MIN_HISTORY, len(df)):
        price = float(closes[t])
        if not np.isfinite(price) or price <= 0:
            continue
        levels = RiskLevels()
        if atr is not None and np.isfinite(atr[t]):
            levels.stop_atr = round(price - 2.0 * float(atr[t]), 2)
        hist = df.iloc[: t + 1]
        levels = calc_support_resistance(hist, price, levels)
        levels = calc_fibonacci(hist, price, levels)
        levels = calc_swing_levels(hist, price, levels)
        levels = calc_fixed_percent(price, levels, 5.0, 8.0)
        out[t] = _parity_select_stop(price, levels)
    return pd.Series(out, index=df.index)


def maybe_apply_parity_stop(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if not _PARITY_STOP:
        return frames
    from bist_bot.indicators import TechnicalIndicators

    out: dict[str, pd.DataFrame] = {}
    for ticker, df in frames.items():
        enriched = TechnicalIndicators.add_all(df.sort_index())
        enriched["stop_loss_atr"] = parity_stop_series(enriched)
        out[ticker] = enriched
    return out


def maybe_apply_stop_cap(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Stop mesafe üst sınırı: 2·ATR stopu script seviyesinde daraltır.

    Çekirdeğe dokunmaz — frame'ler göstergelerle zenginleştirilir ve
    ``stop_loss_atr`` yukarı (girişe yakın) kırpılır; motor rsi/sma
    sütunlarını gördüğü için kendi add_all'ini atlayıp bu stopu kullanır.
    """
    if _STOP_CAP_ATR is None and _STOP_CAP_PCT is None:
        return frames
    from bist_bot.indicators import TechnicalIndicators

    out: dict[str, pd.DataFrame] = {}
    for ticker, df in frames.items():
        enriched = TechnicalIndicators.add_all(df.sort_index())
        raw = enriched["stop_loss_atr"]
        if _STOP_CAP_PCT is not None:
            pct_floor = enriched["close"] * (1 - _STOP_CAP_PCT / 100.0)
            raw = raw.clip(lower=pct_floor)
        if _STOP_CAP_ATR is not None:
            atr_floor = enriched["close"] - _STOP_CAP_ATR * enriched["atr"]
            raw = raw.clip(lower=atr_floor)
        enriched["stop_loss_atr"] = raw
        out[ticker] = enriched
    return out


def load_frames(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    frames = fetch_frames(tickers, period=period)
    frames = maybe_apply_stop_cap(frames)
    return maybe_apply_parity_stop(frames)


def wilson(wr: float, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    den = 1 + z * z / n
    center = wr + z * z / (2 * n)
    margin = z * math.sqrt(wr * (1 - wr) / n + z * z / (4 * n * n))
    return ((center - margin) / den, (center + margin) / den)


def iter_windows(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    """Warmup'lı (train_frame, test_frame, test_start, test_end) üretir.

    - train_frame: [start-WARMUP, train_end-PURGE) — göstergeler ısınmış,
      kuyruk purge'lu; tamamı in-sample.
    - test_frame: [test_start-WARMUP, test_end+EXIT_EXTENSION) + embargo kayması;
      OOS sayımına yalnızca test_start <= entry_date < test_end işlemleri girer
      (çıkış uzatmada çözümlenebilir — FINAL_CLOSE artefaktı önlenir).
    - Sızıntı yok: her karar yalnızca kendi geçmişini görür.
    """
    df = df.sort_index()
    n = len(df)
    start = WARMUP_BARS
    while start + TRAIN_DAYS + TEST_DAYS <= n:
        train_end = start + TRAIN_DAYS
        test_start_pos = train_end + EMBARGO_BARS
        test_end = test_start_pos + TEST_DAYS
        if test_end > n:
            break
        train_frame = df.iloc[max(0, start - WARMUP_BARS) : train_end - PURGE_BARS]
        test_frame = df.iloc[
            max(0, test_start_pos - WARMUP_BARS) : min(n, test_end + EXIT_EXTENSION_BARS)
        ]
        yield (
            train_frame,
            test_frame,
            pd.Timestamp(df.index[test_start_pos]),
            pd.Timestamp(df.index[test_end - 1]),
        )
        start += STEP_DAYS


def pooled_oos_trades(
    params: StrategyParams, frames: dict[str, pd.DataFrame]
) -> list[dict[str, Any]]:
    """Her ticker'da test pencerelerini koşup OOS işlemleri havuzlar."""
    factory = make_factory(params)
    pooled: list[dict[str, Any]] = []
    for ticker, df in frames.items():
        backtester = factory(
            initial_capital=100_000.0,
            cost_model=None,
            commission_buy_pct=None,
            commission_sell_pct=None,
            slippage_pct=None,
            strategy_params=params,
        )
        for _, test_frame, test_start, test_end in iter_windows(df):
            result = backtester.run(ticker, test_frame, verbose=False)
            if result is None:
                continue
            for trade in result.trades:
                entry_ts = pd.Timestamp(trade.entry_date)
                if entry_ts < test_start or entry_ts > test_end:
                    continue  # warmup/uzatma bölgesi girişi — OOS sayılmaz
                row = trade.to_dict()
                row["ticker"] = ticker
                pooled.append(row)
    return pooled


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = [t for t in trades if float(t.get("profit_pct", 0.0)) > 0]
    wr = len(wins) / n
    lo, hi = wilson(wr, n)
    gross_w = [float(t["profit_pct"]) for t in wins]
    gross_l = [float(t["profit_pct"]) for t in trades if float(t.get("profit_pct", 0.0)) <= 0]
    gp = sum(x for x in gross_w)
    gl = -sum(x for x in gross_l)
    return {
        "n": n,
        "win_rate": round(wr * 100, 1),
        "wilson_lo": round(lo * 100, 1),
        "wilson_hi": round(hi * 100, 1),
        "avg_net_pp": round(sum(float(t["profit_pct"]) for t in trades) / n, 3),
        "avg_winner_pp": round(sum(gross_w) / len(gross_w), 3) if gross_w else 0.0,
        "avg_loser_pp": round(sum(gross_l) / len(gross_l), 3) if gross_l else 0.0,
        "profit_factor": round(gp / gl, 3) if gl > 0 else 0.0,
    }


def cmd_diagnose(args: argparse.Namespace) -> int:
    params = StrategyParams.champion_wr()
    frames = load_frames(args.tickers, period=args.period)
    if not frames:
        return 1
    global _MACRO_SERIES
    if _MACRO_MODE != "off":
        frames = {t: normalize_daily_index(df) for t, df in frames.items()}
        _MACRO_SERIES = build_macro_series(frames)
        print(f"Macro series: mode={_MACRO_MODE} bars={len(_MACRO_SERIES)}")
    per_ticker: dict[str, Any] = {}
    factory = make_factory(params)
    all_oos: list[dict[str, Any]] = []
    for ticker, df in frames.items():
        backtester = factory(
            initial_capital=100_000.0,
            cost_model=None,
            commission_buy_pct=None,
            commission_sell_pct=None,
            slippage_pct=None,
            strategy_params=params,
        )
        is_rets: list[float] = []
        oos_trades: list[dict[str, Any]] = []
        n_windows = 0
        for train_frame, test_frame, test_start, test_end in iter_windows(df):
            n_windows += 1
            train_result = backtester.run(ticker, train_frame, verbose=False)
            if train_result is not None:
                is_rets.append(float(train_result.total_return_pct))
            test_result = backtester.run(ticker, test_frame, verbose=False)
            if test_result is None:
                continue
            for trade in test_result.trades:
                entry_ts = pd.Timestamp(trade.entry_date)
                if entry_ts < test_start or entry_ts > test_end:
                    continue
                row = trade.to_dict()
                row["ticker"] = ticker
                oos_trades.append(row)
        all_oos.extend(oos_trades)
        oos_summary = summarize_trades(oos_trades)
        per_ticker[ticker] = {
            "windows": n_windows,
            "oos_trades": oos_summary.get("n", 0),
            "oos_win_rate": oos_summary.get("win_rate"),
            "oos_avg_net_pp": oos_summary.get("avg_net_pp"),
            "is_mean_return": round(sum(is_rets) / len(is_rets), 2) if is_rets else 0.0,
        }
    pooled = all_oos
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "diagnose",
        "params": "champion_wr (buy 28 / sell -28 / cap 33 / pv-gate)",
        "target_rr": _target_rr(),
        "stop_cap": stop_cap_config(),
        "windows": {
            "train": TRAIN_DAYS,
            "test": TEST_DAYS,
            "step": STEP_DAYS,
            "purge": PURGE_BARS,
            "embargo": EMBARGO_BARS,
            "warmup": WARMUP_BARS,
            "exit_extension": EXIT_EXTENSION_BARS,
        },
        "costs": "realistic (15/20/30bps + vergi/harç)",
        "per_ticker": per_ticker,
        "pooled_oos": summarize_trades(pooled),
        "data_fingerprint": {
            "min_last_bar": str(min(pd.Timestamp(df.index[-1]).date() for df in frames.values())),
            "max_last_bar": str(max(pd.Timestamp(df.index[-1]).date() for df in frames.values())),
            "n_tickers": len(frames),
        },
        "pooled_trades": [
            {
                "ticker": t.get("ticker"),
                "entry_date": t.get("entry_date"),
                "exit_date": t.get("exit_date"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "profit_pct": t.get("profit_pct"),
                "exit_reason": t.get("exit_reason"),
                "signal_score": t.get("signal_score"),
            }
            for t in pooled
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pooled_s = summary["pooled_oos"]
    print("=" * 70)
    print(
        f"Pooled OOS: n={pooled_s.get('n')} WR={pooled_s.get('win_rate')}% "
        f"[{pooled_s.get('wilson_lo')}-{pooled_s.get('wilson_hi')}] "
        f"avgNet={pooled_s.get('avg_net_pp')}pp PF={pooled_s.get('profit_factor')}"
    )
    for ticker, row in per_ticker.items():
        print(
            f"  {ticker:<10} win={row.get('windows')} "
            f"OOS_n={row.get('oos_trades')} OOS_WR={row.get('oos_win_rate')} "
            f"OOS_net={row.get('oos_avg_net_pp')} IS_ret={row.get('is_mean_return')}"
        )
    print(f"Summary: {out}")
    return 0


SEARCH_SPACE: dict[str, list[Any]] = {
    # Champion bandı sabit (28-33); optimize edilenler:
    "buy_threshold": [24.0, 28.0, 32.0],
    "adx_threshold": [15.0, 20.0, 25.0],
    "rsi_oversold": [25.0, 30.0, 35.0],
    "pv_confirmation_required": [True, False],
}


def random_candidate(rng: random.Random) -> dict[str, Any]:
    return {key: rng.choice(values) for key, values in SEARCH_SPACE.items()}


def candidate_params(candidate: dict[str, Any]) -> StrategyParams:
    params = StrategyParams.champion_wr()
    for key, value in candidate.items():
        setattr(params, key, value)
    return params


def train_fitness(params: StrategyParams, frames: dict[str, pd.DataFrame]) -> tuple[float, int]:
    """Purge'lu train Tym — cost-aware fitness (net beklenti, min işlem filtresi)."""
    factory = make_factory(params)
    pooled: list[dict[str, Any]] = []
    for ticker, df in frames.items():
        backtester = factory(
            initial_capital=100_000.0,
            cost_model=None,
            commission_buy_pct=None,
            commission_sell_pct=None,
            slippage_pct=None,
            strategy_params=params,
        )
        for train_frame, _, _, _ in iter_windows(df):
            result = backtester.run(ticker, train_frame, verbose=False)
            if result is None:
                continue
            pooled.extend(t.to_dict() for t in result.trades)
    if len(pooled) < 10:
        return (-float("inf"), len(pooled))
    avg_net = sum(float(t["profit_pct"]) for t in pooled) / len(pooled)
    wr = sum(float(t["profit_pct"]) > 0 for t in pooled) / len(pooled)
    # Net beklenti × isabet cezası (WR<%40 aday elenir yönünde baskı).
    fitness = avg_net * (0.5 + wr)
    return (fitness, len(pooled))


def cmd_search(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    frames = load_frames(args.tickers, period=args.period)
    if not frames:
        return 1
    base = StrategyParams.champion_wr()
    tried: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for i in range(args.iters):
        cand = random_candidate(rng)
        params = candidate_params(cand)
        fitness, n_trades = train_fitness(params, frames)
        row = {"iter": i, "candidate": cand, "fitness": round(fitness, 4), "n_trades": n_trades}
        tried.append(row)
        print(f"  [{i + 1}/{args.iters}] fit={row['fitness']:+.3f} n={n_trades} {cand}")
        if best is None or fitness > best["fitness"]:
            best = row
    assert best is not None
    best_params = candidate_params(best["candidate"])
    pooled = pooled_oos_trades(best_params, frames)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "search",
        "seed": args.seed,
        "iters": args.iters,
        "target_rr": _target_rr(),
        "stop_cap": stop_cap_config(),
        "windows": {
            "train": TRAIN_DAYS,
            "test": TEST_DAYS,
            "step": STEP_DAYS,
            "purge": PURGE_BARS,
            "embargo": EMBARGO_BARS,
            "warmup": WARMUP_BARS,
            "exit_extension": EXIT_EXTENSION_BARS,
        },
        "costs": "realistic (15/20/30bps + vergi/harç)",
        "tried": tried,
        "best": best,
        "best_pooled_oos": summarize_trades(pooled),
        "champion_baseline_pooled_oos": summarize_trades(pooled_oos_trades(base, frames)),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 70)
    print(f"Best: {best['candidate']} fit={best['fitness']}")
    print(f"Best pooled OOS : {summary['best_pooled_oos']}")
    print(f"Champion pooled : {summary['champion_baseline_pooled_oos']}")
    print(f"Summary: {out}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Champion recalibration (v2 adım 4).")
    parser.add_argument("--mode", choices=["diagnose", "search"], default="diagnose")
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument(
        "--universe",
        choices=["pilot", "bist100"],
        default="pilot",
        help="pilot: 10 likit; bist100: snapshot evren (default: pilot)",
    )
    parser.add_argument("--period", default="1y")
    parser.add_argument("--iters", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--target-rr",
        type=float,
        default=None,
        help="Hedef RR override (default: FALLBACK_TARGET_RR settings)",
    )
    parser.add_argument(
        "--stop-cap-atr",
        type=float,
        default=None,
        help="Stop mesafe üst sınırı (ATR katı; örn. 1.5). 2·ATR stopu daraltır.",
    )
    parser.add_argument(
        "--stop-cap-pct",
        type=float,
        default=None,
        help="Stop mesafe üst sınırı (fiyat yüzdesi; örn. 4.0).",
    )
    parser.add_argument(
        "--time-stop-bars",
        type=int,
        default=None,
        help="Zaman stopu: girişten N bar sonra TIME_STOP çıkışı (motor max_hold_bars).",
    )
    parser.add_argument(
        "--max-stop-pct",
        type=float,
        default=None,
        help="Giriş filtresi: stopu %X'ten uzak kurulumları atla (örn. 6.0).",
    )
    parser.add_argument(
        "--gap-entry-pct",
        type=float,
        default=None,
        help="Giriş filtresi: açılış boşluğu %X'ten fazla aşağı ise girişi atla (örn. 3.0).",
    )
    parser.add_argument(
        "--gap-entry-atr",
        type=float,
        default=None,
        help="Giriş filtresi: açılış boşluğu X·ATR[t-1]'den fazla aşağı ise atla (örn. 1.5).",
    )
    parser.add_argument(
        "--target-atr-mult",
        type=float,
        default=None,
        help="Ayrık ATR hedef: hedef=close+k·ATR (stop-hedef bağı kopar).",
    )
    parser.add_argument(
        "--parity-stop",
        action="store_true",
        help="Canlı stop-seçim paritesi: destek/fib/swing/%% adayları + MIN_STOP (Adım 1).",
    )
    parser.add_argument(
        "--trailing-mult",
        type=float,
        default=None,
        help="Deney M trailing paritesi: trail=peak_close-mult·ATR (Adım 4).",
    )
    parser.add_argument(
        "--macro-mode",
        choices=["off", "observe", "enforce"],
        default="off",
        help="Makro rejim kapısı: enforce BEAR gün girişlerini keser (Adım 2).",
    )
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "recalibrate_diagnose.json"))
    return parser.parse_args(argv)


def resolve_tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return list(args.tickers)
    if args.universe == "bist100":
        from bist_bot.data.bist100 import BIST100_TICKERS

        return list(BIST100_TICKERS)
    return list(PILOT_TICKERS)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.tickers = resolve_tickers(args)
    global \
        _TARGET_RR_OVERRIDE, \
        _STOP_CAP_ATR, \
        _STOP_CAP_PCT, \
        _TIME_STOP_BARS, \
        _MAX_STOP_PCT, \
        _TARGET_ATR_MULT, \
        _TRAILING_MULT, \
        _PARITY_STOP, \
        _MACRO_MODE, \
        _GAP_ENTRY_PCT, \
        _GAP_ENTRY_ATR
    if args.target_rr is not None:
        if args.target_rr <= 0:
            raise SystemExit("--target-rr must be > 0")
        _TARGET_RR_OVERRIDE = float(args.target_rr)
    if args.stop_cap_atr is not None:
        if args.stop_cap_atr <= 0:
            raise SystemExit("--stop-cap-atr must be > 0")
        _STOP_CAP_ATR = float(args.stop_cap_atr)
    if args.stop_cap_pct is not None:
        if args.stop_cap_pct <= 0:
            raise SystemExit("--stop-cap-pct must be > 0")
        _STOP_CAP_PCT = float(args.stop_cap_pct)
    if args.time_stop_bars is not None:
        if args.time_stop_bars < 1:
            raise SystemExit("--time-stop-bars must be >= 1")
        _TIME_STOP_BARS = int(args.time_stop_bars)
    if args.max_stop_pct is not None:
        if args.max_stop_pct <= 0:
            raise SystemExit("--max-stop-pct must be > 0")
        _MAX_STOP_PCT = float(args.max_stop_pct)
    if args.gap_entry_pct is not None:
        if args.gap_entry_pct <= 0:
            raise SystemExit("--gap-entry-pct must be > 0")
        _GAP_ENTRY_PCT = float(args.gap_entry_pct)
    if args.gap_entry_atr is not None:
        if args.gap_entry_atr <= 0:
            raise SystemExit("--gap-entry-atr must be > 0")
        _GAP_ENTRY_ATR = float(args.gap_entry_atr)
    if args.target_atr_mult is not None:
        if args.target_atr_mult <= 0:
            raise SystemExit("--target-atr-mult must be > 0")
        _TARGET_ATR_MULT = float(args.target_atr_mult)
    if args.trailing_mult is not None:
        if args.trailing_mult <= 0:
            raise SystemExit("--trailing-mult must be > 0")
        _TRAILING_MULT = float(args.trailing_mult)
    if args.parity_stop:
        _PARITY_STOP = True
    if args.macro_mode != "off":
        _MACRO_MODE = args.macro_mode
    if args.mode == "diagnose":
        return cmd_diagnose(args)
    return cmd_search(args)


if __name__ == "__main__":
    raise SystemExit(main())
