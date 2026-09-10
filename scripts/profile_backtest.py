"""Standalone backtest profiler (Aşama 1, Adım 4).

Deterministik sentetik OHLCV üzerinde gerçek indikatör hattıyla Backtester
(vektör + iteratif yol) ve WalkForwardValidator senaryolarını ölçer.

- Ağ erişimi, DB yazımı, Telegram yan etkisi üretmez; ``results/`` altına
  okuma/yazma yapmaz (``--output`` ile ``results/`` içi bir yol verilirse
  reddedilir).
- Warm-up koşusu ölçüme dahil değildir; ``--duration-sec`` yumuşak bütçedir
  (çalışan koşu yarıda kesilmez).
- Karşılaştırma için ``--runs`` ile sabit koşu sayısı da verilebilir.

Kullanım:
    python scripts/profile_backtest.py --tickers 10 --duration-sec 30
    python scripts/profile_backtest.py --scenario engine-iterative --runs 3
"""

from __future__ import annotations

import argparse
import cProfile
import logging
import os
import pstats
import subprocess
import sys
from datetime import datetime
from io import StringIO
from time import perf_counter

import numpy as np
import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from bist_bot.backtest import Backtester  # noqa: E402
from bist_bot.backtest.walkforward import WalkForwardValidator  # noqa: E402
from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.strategy.params import StrategyParams  # noqa: E402

# Hedef sıcak kod yolları (rapor bunların gerçekten koştuğunu doğrular).
TARGET_PATHS = (
    "backtest/engine.py:_precalculate_signals",
    "backtest/engine.py:_run_vectorized",
    "backtest/engine.py:_run_iterative",
    "backtest/walkforward.py:run",
)


def build_synthetic_ohlcv(tickers: int, bars: int, seed: int) -> dict[str, pd.DataFrame]:
    """Deterministik, rejim-karışık sentetik günlük OHLCV üretir."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(datetime(2020, 1, 2), periods=bars, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for t in range(tickers):
        drift = rng.uniform(-0.15, 0.25)
        vol = rng.uniform(0.8, 2.2)
        rets = rng.normal(drift / 100.0, vol / 100.0, bars)
        # Rejim karışımı: ilk yarı trend, ikinci yarı yatay-dalgalı.
        rets[: bars // 2] += abs(drift) / 100.0
        rets[bars // 2 :] *= 1.4
        close = 100.0 * np.exp(np.cumsum(rets))
        spread = np.abs(rng.normal(0.4, 0.2, bars)) + 0.1
        high = close + spread
        low = close - spread
        open_ = close + rng.normal(0.0, 0.15, bars)
        volume = rng.integers(5_000, 200_000, bars).astype(float)
        out[f"SYN{t:02d}.IS"] = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=dates,
        )
    return out


def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.stdout.strip() or "bilinmiyor"
    except Exception:
        return "bilinmiyor"


def _scenario_engine(frames: dict[str, pd.DataFrame], force_iterative: bool) -> dict:
    """Backtester senaryosu; ayar + koşu sayacı döndürür."""
    params = StrategyParams.from_settings()
    backtester = Backtester(initial_capital=100_000.0, strategy_params=params)
    with settings.override(BACKTEST_FORCE_ITERATIVE=force_iterative):
        selected = "iterative" if not backtester._use_vectorized_path() else "vectorized"

    def _run_once() -> int:
        trades = 0
        with settings.override(BACKTEST_FORCE_ITERATIVE=force_iterative):
            for ticker, df in frames.items():
                result = backtester.run(ticker, df, verbose=False)
                if result is not None:
                    trades += int(result.total_trades)
        return trades

    _run_once()  # warm-up (ölçülmez)
    return {"runner": _run_once, "path": selected, "params": params}


def _scenario_walkforward(frames: dict[str, pd.DataFrame], use_real_optimizer: bool) -> dict:
    params = StrategyParams.from_settings()

    class _StubOptimizer:
        """Sabit params döndürür: pencere döngüsü + pencere-backtest hattı
        ölçülür (optimizer arama maliyeti Aşama 2 konusudur)."""

        def random_search(self, param_grid, n_iter=4):
            return StrategyParams.conservative(), None

    validator = WalkForwardValidator(
        # Test penceresi min_trigger_candles=30 eşiğini geçmeli (2 ay ≈ 46 bar);
        # aksi halde hiçbir pencerede işlem üretilemez (ölçüm boşa gider).
        train_window=3,
        test_window=2,
        step=2,
        optimizer_iterations=4,
        param_grid={
            "buy_threshold": [20.0, 25.0],
            "sell_threshold": [-20.0, -25.0],
        },
        optimizer_factory=None if use_real_optimizer else (lambda t, d, c: _StubOptimizer()),
    )
    tickers = list(frames)
    attempted: list[int] = []
    completed: list[int] = []

    def _run_once() -> int:
        tried = 0
        done = 0
        for ticker in tickers:
            tried += len(validator._build_windows(frames[ticker].sort_index()))
            result = validator.run(ticker, frames[ticker], initial_capital=100_000.0)
            if result is not None:
                done += len(result.windows)
        attempted.append(tried)
        completed.append(done)
        return tried

    _run_once()  # warm-up (ölçülmez)
    attempted.clear()
    completed.clear()

    def _note() -> str:
        return (
            f"pencere denemesi: {sum(attempted)} / tamamlanan: {sum(completed)} "
            "(sentetik veri sinyal üretmezse işlem hattı maliyeti ölçülmez, "
            "yalnızca pencere döngüsü maliyeti)"
        )

    return {"runner": _run_once, "path": "walkforward", "params": params, "note": _note}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[rank]


def _run_scenario(
    name: str,
    scenario: dict,
    bars_per_run: int,
    duration_sec: float,
    runs: int | None,
    top_n: int,
) -> dict:
    runner = scenario["runner"]
    path = scenario["path"]
    durations: list[float] = []
    units_total = 0
    runs_done = 0
    profiler = cProfile.Profile()
    seen: set[str] = set()
    started_all = perf_counter()
    while True:
        profiler.enable()
        started = perf_counter()
        try:
            units_total += runner()
        finally:
            profiler.disable()
        durations.append(perf_counter() - started)
        runs_done += 1
        if runs is not None and runs_done >= runs:
            break
        if runs is None and (perf_counter() - started_all) >= duration_sec:
            break
    total = sum(durations)
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("tottime")
    stats.print_stats(top_n)
    for func in stats.stats:
        filename, _lineno, funcname = func
        short = os.path.basename(filename)
        for target in TARGET_PATHS:
            tfile, tfunc = target.split(":")
            if short == os.path.basename(tfile) and funcname == tfunc:
                seen.add(target)
    return {
        "name": name,
        "path": path,
        "runs": runs_done,
        "units": units_total,
        "total_sec": total,
        "bars_per_run": bars_per_run,
        "median_sec": _percentile(durations, 50),
        "p95_sec": _percentile(durations, 95),
        "bars_per_sec": (bars_per_run * runs_done / total) if total > 0 else 0.0,
        "stats": stream.getvalue(),
        "seen_paths": sorted(seen),
        "note": scenario.get("note", lambda: "")(),
    }


def _refuse_results_dir(path: str) -> str:
    resolved = os.path.abspath(path)
    results_dir = os.path.abspath(os.path.join(ROOT_DIR, "results"))
    if resolved == results_dir or resolved.startswith(results_dir + os.sep):
        raise SystemExit(f"reddedildi: --output results/ altında olamaz: {path}")
    return resolved


def main() -> None:
    # Windows cp1252 konsolunda Türkçe karakter çökmesin (stdout best-effort).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Backtest profiler (Aşama 1).")
    parser.add_argument("--tickers", type=int, default=10)
    parser.add_argument("--bars", type=int, default=260)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--duration-sec", type=float, default=30.0)
    parser.add_argument(
        "--runs",
        type=int,
        default=None,
        help="Sabit koşu sayısı (verilirse --duration-sec geçersiz).",
    )
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "engine-vectorized", "engine-iterative", "walkforward"],
    )
    parser.add_argument("--strategy-profile", default=None)
    parser.add_argument(
        "--wf-optimizer",
        default="stub",
        choices=["stub", "real"],
        help="stub: sabit params ile pencere döngüsünü ölçer (varsayılan); "
        "real: gerçek random_search maliyetini ölçer (sentetik "
        "veride pencere üretemeyebilir).",
    )
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument("--output", default=None, help="Rapor dosyası (results/ dışı).")
    args = parser.parse_args()

    if args.output is not None:
        _refuse_results_dir(args.output)

    profile_override = {"STRATEGY_PROFILE": args.strategy_profile} if args.strategy_profile else {}
    # Konsol log I/O darboğaz ölçümünü kirletmesin diye warm-up dahil tüm
    # koşular boyunca CRITICAL altı susturulur (hesap hattı değişmez).
    logging.disable(logging.CRITICAL)
    try:
        with settings.override(**profile_override):
            frames = build_synthetic_ohlcv(args.tickers, args.bars, args.seed)
            profile_name = getattr(settings, "STRATEGY_PROFILE", "conservative")
            params = StrategyParams.from_settings()
            scenarios: list[tuple[str, dict]] = []
            if args.scenario in ("all", "engine-vectorized"):
                scenarios.append(("engine-vectorized", _scenario_engine(frames, False)))
            if args.scenario in ("all", "engine-iterative"):
                scenarios.append(("engine-iterative", _scenario_engine(frames, True)))
            if args.scenario in ("all", "walkforward"):
                scenarios.append(
                    ("walkforward", _scenario_walkforward(frames, args.wf_optimizer == "real"))
                )

            bars_per_run = args.tickers * args.bars
            results = [
                _run_scenario(name, sc, bars_per_run, args.duration_sec, args.runs, args.top_n)
                for name, sc in scenarios
            ]
    finally:
        logging.disable(logging.NOTSET)

    lines = [
        "== backtest profili ==",
        f"python: {sys.version.split()[0]} | platform: {sys.platform} | commit: {_git_commit()}",
        f"seed: {args.seed} | ticker: {args.tickers} | bar/ticker: {args.bars}",
        f"profil: {profile_name} | buy_threshold: {params.buy_threshold} | "
        f"max_actionable: {params.max_actionable_score} | log: CRITICAL-susturuculu",
        "",
    ]
    for res in results:
        unit_label = "pencere" if res["path"] == "walkforward" else "işlem"
        lines += [
            f"-- {res['name']} (yol: {res['path']}) --",
            f"koşu: {res['runs']} | toplam süre: {res['total_sec']:.2f} sn | "
            f"medyan: {res['median_sec']:.3f} sn | p95: {res['p95_sec']:.3f} sn",
            f"throughput: {res['bars_per_sec']:.0f} bar/sn | toplam {unit_label}: {res['units']}",
            f"hedef yollar: {', '.join(res['seen_paths']) if res['seen_paths'] else 'HİÇBİRİ GÖRÜLMEDİ'}",
        ]
        if res.get("note"):
            lines.append(res["note"])
        lines += [
            "en pahalı fonksiyonlar (tottime):",
            res["stats"].rstrip(),
            "",
        ]
    # cumtime toplamları iç içe çağrılarda üst üste biner; bağımsız maliyet
    # gibi okunmamalıdır (tottime sütunu esas alınır).
    report = "\n".join(lines)
    print(report)
    if args.output is not None:
        with open(_refuse_results_dir(args.output), "w", encoding="utf-8") as fh:
            fh.write(report + "\n")


if __name__ == "__main__":
    main()
