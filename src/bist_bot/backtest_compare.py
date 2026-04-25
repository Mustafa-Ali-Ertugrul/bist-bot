"""
backtest_compare.py

Eski backtest mantigi (basit RSI/SMA/MACD/BB skoru) ile
yeni StrategyEngine mantigini (regime-aware, sector-limit, swing fix)
ayni veri uzerinde calistirir ve karsilastirmali rapor uretir.

Kullanim:
    python backtest_compare.py
    python backtest_compare.py --tickers THYAO.IS ASELS.IS --period 1y
"""

import argparse
import logging
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bist_bot.app_logging import configure_logging
from bist_bot.backtest import Backtester, StrategyBacktester, compare_benchmark
from bist_bot.config.settings import settings
from bist_bot.data.fetcher import BISTDataFetcher
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy import StrategyEngine
from bist_bot.strategy.regime import MarketRegime, detect_regime

logger = logging.getLogger(__name__)


@dataclass
class CompareRow:
    ticker: str
    old_return: float
    new_return: float
    old_trades: int
    new_trades: int
    old_win_rate: float
    new_win_rate: float
    old_drawdown: float
    new_drawdown: float
    old_sharpe: float
    new_sharpe: float
    benchmark_return: float
    sideways_bars_pct: float


def _sideways_pct(df: pd.DataFrame) -> float:
    ti = TechnicalIndicators()
    df = ti.add_all(df).dropna(subset=["rsi", f"sma_{settings.SMA_SLOW}"])
    start = min(50, len(df))
    regimes = [detect_regime(df.iloc[: i + 1]) for i in range(start, len(df))]
    if not regimes:
        return 0.0
    sideways = sum(1 for r in regimes if r == MarketRegime.SIDEWAYS)
    return round(sideways / len(regimes) * 100, 1)


def _print_comparison(rows: list[CompareRow]) -> None:
    W = 110
    print("\n" + "═" * W)
    print("  BACKTEST KARSILASTIRMA: ESKI vs YENI MANTIK")
    print("═" * W)

    header = (
        f"{'Ticker':<12}"
        f"{'Eski Getiri':>12}{'Yeni Getiri':>12}"
        f"{'Δ Getiri':>10}"
        f"{'EskiTrade':>10}{'YeniTrade':>10}"
        f"{'Eski WR':>9}{'Yeni WR':>9}"
        f"{'Eski DD':>9}{'Yeni DD':>9}"
        f"{'Eski SR':>9}{'Yeni SR':>9}"
        f"{'Bench':>8}"
        f"{'YATAY%':>8}"
    )
    print(header)
    print("─" * W)

    for r in rows:
        delta = r.new_return - r.old_return
        delta_str = f"{delta:+.1f}%"
        print(
            f"{r.ticker:<12}"
            f"{r.old_return:>+11.1f}%{r.new_return:>+11.1f}%"
            f"{delta_str:>10}"
            f"{r.old_trades:>10}{r.new_trades:>10}"
            f"{r.old_win_rate:>8.1f}%{r.new_win_rate:>8.1f}%"
            f"{r.old_drawdown:>8.1f}%{r.new_drawdown:>8.1f}%"
            f"{r.old_sharpe:>9.2f}{r.new_sharpe:>9.2f}"
            f"{r.benchmark_return:>+7.1f}%"
            f"{r.sideways_bars_pct:>7.1f}%"
        )

    print("─" * W)

    if rows:
        improved = sum(1 for r in rows if r.new_return > r.old_return)
        avg_delta = np.mean([r.new_return - r.old_return for r in rows])
        avg_trade_change = np.mean([r.new_trades - r.old_trades for r in rows])
        avg_wr_change = np.mean([r.new_win_rate - r.old_win_rate for r in rows])

        print(f"\n  Özet: {improved}/{len(rows)} hissede yeni mantık daha iyi getiri sağladı")
        print(f"  Ort. getiri farkı  : {avg_delta:+.2f}%")
        print(f"  Ort. işlem farkı   : {avg_trade_change:+.1f} (negatif = daha az false positive)")
        print(f"  Ort. win rate farkı: {avg_wr_change:+.1f}%")

    print("═" * W + "\n")


def run_slippage_sweep(
    ticker: str,
    df: pd.DataFrame,
    penalties: list[float] | tuple[float, ...] = (0.0, 0.15, 0.50),
) -> pd.DataFrame:
    """Stress test strategy sensitivity against multiple slippage penalties."""
    logger.warning("\n🧹 %s için slippage sweep başlıyor...", ticker)
    results: list[dict[str, float | int]] = []

    for penalty in penalties:
        with settings.override(SLIPPAGE_PENALTY_RATIO=float(penalty)):
            backtester = StrategyBacktester(engine=StrategyEngine())
            result = backtester.run(ticker, df.copy(), verbose=False)
            if result is None:
                continue

            results.append(
                {
                    "Penalty (ATR Multiplier)": float(penalty),
                    "Total Return (%)": round(result.total_return_pct, 2),
                    "Trades": int(result.total_trades),
                    "Win Rate (%)": round(result.win_rate, 2),
                    "Sharpe": round(result.sharpe_ratio, 2),
                    "Max Drawdown (%)": round(result.max_drawdown_pct, 2),
                }
            )

    sweep_df = pd.DataFrame(results)
    print("\n" + "=" * 60)
    print(f"📊 SLIPPAGE SWEEP SONUÇLARI: {ticker}")
    print("=" * 60)
    if sweep_df.empty:
        print("Sonuç üretilemedi.")
    else:
        print(sweep_df.to_string(index=False))
    print("=" * 60 + "\n")
    return sweep_df


def run(tickers: list[str], period: str = "1y") -> list[CompareRow]:
    fetcher = BISTDataFetcher()
    old_bt = Backtester(
        initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0),
        buy_threshold=settings.BUY_THRESHOLD,
        sell_threshold=settings.SELL_THRESHOLD,
    )
    new_bt = StrategyBacktester(
        initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0),
    )

    rows: list[CompareRow] = []

    for ticker in tickers:
        print(f"  Çekiliyor: {ticker} ({period})...", end=" ", flush=True)
        df = fetcher.fetch_single(ticker, period=period)
        if df is None or len(df) < 60:
            print("yetersiz veri, atlandı.")
            continue

        old_result = old_bt.run(ticker, df.copy(), verbose=False)
        new_result = new_bt.run(ticker, df.copy(), verbose=False)

        if old_result is None or new_result is None:
            print("backtest başarısız, atlandı.")
            continue

        bench = 0.0
        try:
            bench = compare_benchmark(ticker, df)
        except Exception:
            pass

        sw_pct = 0.0
        try:
            sw_pct = _sideways_pct(df.copy())
        except Exception:
            pass

        rows.append(
            CompareRow(
                ticker=ticker,
                old_return=old_result.total_return_pct,
                new_return=new_result.total_return_pct,
                old_trades=old_result.total_trades,
                new_trades=new_result.total_trades,
                old_win_rate=old_result.win_rate,
                new_win_rate=new_result.win_rate,
                old_drawdown=old_result.max_drawdown_pct,
                new_drawdown=new_result.max_drawdown_pct,
                old_sharpe=old_result.sharpe_ratio,
                new_sharpe=new_result.sharpe_ratio,
                benchmark_return=bench,
                sideways_bars_pct=sw_pct,
            )
        )
        print("tamam.")

    return rows


def main():
    configure_logging(level=logging.WARNING, log_file=None, fmt="%(levelname)s | %(message)s")
    parser = argparse.ArgumentParser(description="Eski vs Yeni backtest karşılaştırması")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=["THYAO.IS", "ASELS.IS", "GARAN.IS", "SASA.IS", "BIMAS.IS"],
        help="Karşılaştırılacak hisseler (varsayılan: 5 adet)",
    )
    parser.add_argument(
        "--period",
        default="1y",
        help="yfinance periyot (ör: 6mo, 1y, 2y) (varsayılan: 1y)",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Her ticker için slippage sweep stres testi çalıştır",
    )
    parser.add_argument(
        "--penalties",
        nargs="+",
        type=float,
        default=[0.0, 0.15, 0.50],
        help="Sweep sırasında kullanılacak slippage penalty değerleri",
    )
    args = parser.parse_args()

    print(f"\n  Karşılaştırılacak hisseler: {', '.join(args.tickers)}")
    print(f"  Periyot: {args.period}\n")

    rows = run(args.tickers, args.period)

    if not rows:
        print("Hiç sonuç üretilemedi.")
        sys.exit(1)

    _print_comparison(rows)

    if args.sweep:
        fetcher = BISTDataFetcher()
        for ticker in args.tickers:
            df = fetcher.fetch_single(ticker, period=args.period)
            if df is None or len(df) < 60:
                print(f"Sweep atlandı: {ticker} için veri yetersiz.")
                continue
            run_slippage_sweep(ticker, df, penalties=args.penalties)


if __name__ == "__main__":
    main()
