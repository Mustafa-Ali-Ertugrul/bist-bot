"""
backtest_compare.py

Eski backtest mantigi (basit RSI/SMA/MACD/BB skoru) ile
yeni StrategyEngine mantigini (regime-aware, sector-limit, swing fix)
ayni veri uzerinde calistirir ve karsilastirmali rapor uretir.

Kullanim:
    python backtest_compare.py
    python backtest_compare.py --tickers THYAO.IS ASELS.IS --period 1y
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

import config
from backtest import Backtester, BacktestResult, compare_benchmark
from data_fetcher import BISTDataFetcher
from indicators import TechnicalIndicators
from strategy import StrategyEngine, SignalType

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(message)s",
)
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


class NewEngineBacktester:
    """
    Yeni StrategyEngine'i kullanarak walk-forward tarzı backtest yapar.
    Her bar için sub_df üzerinden analyze() çağırır; sector_limit kapalı
    (tekil analiz modu), reset_sectors() her trade döngüsünde yok.
    """

    def __init__(self, initial_capital: float = None):
        self.initial_capital = initial_capital or getattr(config, "INITIAL_CAPITAL", 8500.0)
        self.commission_pct = (
            getattr(config, "COMMISSION_BUY", 0.0002)
            + getattr(config, "COMMISSION_SELL", 0.0002)
            + getattr(config, "BSMV", 0.0005)
        )
        self.slippage_pct = getattr(config, "SLIPPAGE", 0.001)
        self.sell_threshold = getattr(config, "SELL_THRESHOLD", -10)
        self.indicators = TechnicalIndicators()
        self.engine = StrategyEngine()

    def run(self, ticker: str, df: pd.DataFrame) -> Optional[BacktestResult]:
        if df is None or len(df) < 50:
            return None

        df = self.indicators.add_all(df)
        df = df.dropna(subset=["rsi", f"sma_{config.SMA_SLOW}"])

        capital = self.initial_capital
        position = None
        trades = []
        capital_history = []
        last_buy_date = None

        for i in range(len(df)):
            row = df.iloc[i]
            date = df.index[i]
            price = float(row["close"])

            sub_df = df.iloc[: i + 1]

            capital_history.append(
                capital
                if position is None
                else capital + position["shares"] * price
            )

            signal = self.engine.analyze(ticker, sub_df, enforce_sector_limit=False)

            if position is None:
                if signal and signal.signal_type in {
                    SignalType.STRONG_BUY,
                    SignalType.BUY,
                }:
                    if last_buy_date and (date - last_buy_date).days < 1:
                        continue

                    buy_price = price * (1 + self.slippage_pct)
                    effective_capital = capital * (1 - self.commission_pct)
                    shares = int(effective_capital / buy_price)

                    if shares > 0:
                        cost = shares * buy_price * (1 + self.commission_pct)
                        last_buy_date = date
                        stop = signal.stop_loss if signal.stop_loss > 0 else price * 0.95
                        position = {
                            "entry_date": date,
                            "entry_price": price,
                            "shares": shares,
                            "cost": cost,
                            "stop_loss": stop,
                            "score": signal.score,
                        }
                        capital -= cost

            else:
                sell = False
                if price <= position["stop_loss"]:
                    sell = True
                elif signal and signal.signal_type in {
                    SignalType.SELL,
                    SignalType.STRONG_SELL,
                }:
                    sell = True
                elif signal and signal.score <= self.sell_threshold:
                    sell = True

                if sell:
                    sell_price = price * (1 - self.slippage_pct)
                    revenue = position["shares"] * sell_price * (1 - self.commission_pct)
                    profit_tl = revenue - position["cost"]
                    profit_pct = (profit_tl / position["cost"]) * 100
                    holding_days = (date - position["entry_date"]).days

                    from backtest import BacktestTrade
                    trades.append(
                        BacktestTrade(
                            entry_date=position["entry_date"],
                            exit_date=date,
                            ticker=ticker,
                            entry_price=position["entry_price"],
                            exit_price=price,
                            signal_score=position["score"],
                            profit_pct=round(profit_pct, 2),
                            profit_tl=round(profit_tl, 2),
                            holding_days=holding_days,
                        )
                    )
                    capital += revenue
                    position = None

        if position is not None:
            last_price = float(df.iloc[-1]["close"])
            revenue = position["shares"] * last_price * (1 - self.commission_pct)
            profit_tl = revenue - position["cost"]
            profit_pct = (profit_tl / position["cost"]) * 100
            from backtest import BacktestTrade
            trades.append(
                BacktestTrade(
                    entry_date=position["entry_date"],
                    exit_date=df.index[-1],
                    ticker=ticker,
                    entry_price=position["entry_price"],
                    exit_price=last_price,
                    signal_score=position["score"],
                    profit_pct=round(profit_pct, 2),
                    profit_tl=round(profit_tl, 2),
                    holding_days=(df.index[-1] - position["entry_date"]).days,
                )
            )
            capital += revenue

        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        winning = [t for t in trades if t.profit_pct > 0]
        losing = [t for t in trades if t.profit_pct <= 0]

        cap_series = pd.Series(capital_history)
        rolling_max = cap_series.cummax()
        drawdown = (cap_series - rolling_max) / rolling_max * 100
        max_dd = float(drawdown.min())

        sharpe = 0.0
        if len(trades) > 1:
            returns = [t.profit_pct for t in trades]
            std = np.std(returns)
            if std > 0:
                sharpe = np.mean(returns) / std * np.sqrt(252)

        return BacktestResult(
            ticker=ticker,
            period=f"{df.index[0].strftime('%d.%m.%Y')} → {df.index[-1].strftime('%d.%m.%Y')}",
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            total_return_pct=round(total_return, 2),
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=round(len(winning) / len(trades) * 100, 1) if trades else 0,
            avg_profit_pct=round(np.mean([t.profit_pct for t in winning]), 2) if winning else 0,
            avg_loss_pct=round(np.mean([t.profit_pct for t in losing]), 2) if losing else 0,
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            trades=trades,
        )


def _sideways_pct(df: pd.DataFrame) -> float:
    from strategy import detect_regime, MarketRegime
    ti = TechnicalIndicators()
    df = ti.add_all(df).dropna(subset=["rsi", f"sma_{config.SMA_SLOW}"])
    start = min(50, len(df))
    regimes = [detect_regime(df.iloc[:i+1]) for i in range(start, len(df))]
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

        print(
            f"\n  Özet: {improved}/{len(rows)} hissede yeni mantık daha iyi getiri sağladı"
        )
        print(f"  Ort. getiri farkı  : {avg_delta:+.2f}%")
        print(f"  Ort. işlem farkı   : {avg_trade_change:+.1f} (negatif = daha az false positive)")
        print(f"  Ort. win rate farkı: {avg_wr_change:+.1f}%")

    print("═" * W + "\n")


def run(tickers: list[str], period: str = "1y") -> list[CompareRow]:
    fetcher = BISTDataFetcher()
    old_bt = Backtester(
        initial_capital=getattr(config, "INITIAL_CAPITAL", 8500.0),
        buy_threshold=getattr(config, "BUY_THRESHOLD", 10),
        sell_threshold=getattr(config, "SELL_THRESHOLD", -10),
    )
    new_bt = NewEngineBacktester(
        initial_capital=getattr(config, "INITIAL_CAPITAL", 8500.0),
    )

    rows: list[CompareRow] = []

    for ticker in tickers:
        print(f"  Çekiliyor: {ticker} ({period})...", end=" ", flush=True)
        df = fetcher.fetch_single(ticker, period=period)
        if df is None or len(df) < 60:
            print("yetersiz veri, atlandı.")
            continue

        old_result = old_bt.run(ticker, df.copy(), verbose=False)
        new_result = new_bt.run(ticker, df.copy())

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
    args = parser.parse_args()

    print(f"\n  Karşılaştırılacak hisseler: {', '.join(args.tickers)}")
    print(f"  Periyot: {args.period}\n")

    rows = run(args.tickers, args.period)

    if not rows:
        print("Hiç sonuç üretilemedi.")
        sys.exit(1)

    _print_comparison(rows)


if __name__ == "__main__":
    main()
