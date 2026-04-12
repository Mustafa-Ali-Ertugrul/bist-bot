import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

try:
    import yfinance as yf
except ImportError:
    yf = None

import config
from indicators import TechnicalIndicators
from strategy import StrategyEngine, SignalType

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    entry_date: datetime
    exit_date: datetime
    ticker: str
    entry_price: float
    exit_price: float
    signal_score: float
    profit_pct: float
    profit_tl: float
    holding_days: int


@dataclass
class BacktestResult:
    ticker: str
    period: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit_pct: float
    avg_loss_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: list[BacktestTrade] = field(default_factory=list)

    def __str__(self):
        return (
            f"\n{'═'*55}\n"
            f"📊 BACKTEST SONUCU: {self.ticker}\n"
            f"{'═'*55}\n"
            f"  Periyot         : {self.period}\n"
            f"  Başlangıç       : ₺{self.initial_capital:,.2f}\n"
            f"  Bitiş           : ₺{self.final_capital:,.2f}\n"
            f"  Toplam Getiri   : %{self.total_return_pct:.2f}\n"
            f"  ─────────────────────────────\n"
            f"  Toplam İşlem    : {self.total_trades}\n"
            f"  Kazanan         : {self.winning_trades}\n"
            f"  Kaybeden        : {self.losing_trades}\n"
            f"  Kazanma Oranı   : %{self.win_rate:.1f}\n"
            f"  ─────────────────────────────\n"
            f"  Ort. Kâr        : %{self.avg_profit_pct:.2f}\n"
            f"  Ort. Zarar      : %{self.avg_loss_pct:.2f}\n"
            f"  Max Drawdown    : %{self.max_drawdown_pct:.2f}\n"
            f"  Sharpe Ratio    : {self.sharpe_ratio:.2f}\n"
            f"{'═'*55}"
        )


class Backtester:
    def __init__(
        self,
        initial_capital: float = 8500.0,
        commission_pct: float = 0.002,
        buy_threshold: float = 35,
        sell_threshold: float = -15,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = 0.001
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.last_buy_date = None
        self.indicators = TechnicalIndicators()
        self.engine = StrategyEngine()

    def run(
        self,
        ticker: str,
        df: pd.DataFrame,
        verbose: bool = True
    ) -> Optional[BacktestResult]:
        if df is None or len(df) < 50:
            logger.warning(f"  Yetersiz veri: {len(df) if df is not None else 0}")
            return None

        df = self.indicators.add_all(df)

        df = df.dropna(subset=["rsi", f"sma_{config.SMA_SLOW}"])

        capital = self.initial_capital
        position = None
        trades: list[BacktestTrade] = []
        capital_history = []

        for i in range(len(df)):
            row = df.iloc[i]
            date = df.index[i]
            price = row["close"]

            sub_df = df.iloc[:i+1]
            score = self._calculate_score(sub_df)

            capital_history.append(
                capital if position is None
                else capital + (price - position["entry_price"])
                     * position["shares"]
            )

            if position is None:
                if score >= self.buy_threshold:
                    if self.last_buy_date is not None and (date - self.last_buy_date).days < 1:
                        continue
                    
                    buy_price = price * (1 + self.slippage_pct)
                    effective_capital = capital * (1 - self.commission_pct)
                    shares = int(effective_capital / buy_price)

                    if shares > 0:
                        cost = shares * buy_price * (1 + self.commission_pct)
                        self.last_buy_date = date
                        position = {
                            "entry_date": date,
                            "entry_price": price,
                            "shares": shares,
                            "cost": cost,
                            "stop_loss": row.get(
                                "stop_loss_atr", price * 0.95
                            ),
                            "score": score,
                        }
                        capital -= cost

                        if verbose:
                            logger.info(
                                f"  🟢 AL: {date.strftime('%d.%m')} | "
                                f"₺{price:.2f} x {shares} lot | "
                                f"Skor: {score:+.0f}"
                            )

            else:
                sell = False
                reason = ""

                if price <= position["stop_loss"]:
                    sell = True
                    reason = "STOP-LOSS"

                elif score <= self.sell_threshold:
                    sell = True
                    reason = "SİNYAL"

                if sell:
                    sell_price = price * (1 - self.slippage_pct)
                    revenue = (
                        position["shares"] * sell_price
                        * (1 - self.commission_pct)
                    )
                    profit_tl = revenue - position["cost"]
                    profit_pct = (profit_tl / position["cost"]) * 100
                    holding_days = (date - position["entry_date"]).days

                    trade = BacktestTrade(
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
                    trades.append(trade)

                    capital += revenue
                    position = None

                    if verbose:
                        emoji = "✅" if profit_tl > 0 else "❌"
                        logger.info(
                            f"  🔴 SAT ({reason}): "
                            f"{date.strftime('%d.%m')} | "
                            f"₺{price:.2f} | "
                            f"{emoji} {profit_pct:+.1f}% "
                            f"(₺{profit_tl:+.0f}) | "
                            f"{holding_days} gün"
                        )

        if position is not None:
            last_price = df.iloc[-1]["close"]
            revenue = (
                position["shares"] * last_price
                * (1 - self.commission_pct)
            )
            profit_tl = revenue - position["cost"]
            profit_pct = (profit_tl / position["cost"]) * 100

            trades.append(BacktestTrade(
                entry_date=position["entry_date"],
                exit_date=df.index[-1],
                ticker=ticker,
                entry_price=position["entry_price"],
                exit_price=last_price,
                signal_score=position["score"],
                profit_pct=round(profit_pct, 2),
                profit_tl=round(profit_tl, 2),
                holding_days=(df.index[-1] - position["entry_date"]).days,
            ))
            capital += revenue

        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        winning = [t for t in trades if t.profit_pct > 0]
        losing = [t for t in trades if t.profit_pct <= 0]

        cap_series = pd.Series(capital_history)
        rolling_max = cap_series.cummax()
        drawdown = (cap_series - rolling_max) / rolling_max * 100
        max_dd = float(drawdown.min())

        if len(trades) > 1:
            returns = [t.profit_pct for t in trades]
            sharpe = (
                np.mean(returns) / np.std(returns) * np.sqrt(252)
                if np.std(returns) > 0 else 0
            )
        else:
            sharpe = 0

        result = BacktestResult(
            ticker=ticker,
            period=f"{df.index[0].strftime('%d.%m.%Y')} → "
                   f"{df.index[-1].strftime('%d.%m.%Y')}",
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            total_return_pct=round(total_return, 2),
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=round(
                len(winning) / len(trades) * 100, 1
            ) if trades else 0,
            avg_profit_pct=round(
                np.mean([t.profit_pct for t in winning]), 2
            ) if winning else 0,
            avg_loss_pct=round(
                np.mean([t.profit_pct for t in losing]), 2
            ) if losing else 0,
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            trades=trades,
        )

        return result

    def _calculate_score(self, df: pd.DataFrame) -> float:
        if len(df) < 2:
            return 0

        last = df.iloc[-1]
        score = 0.0

        rsi = last.get("rsi")
        if pd.notna(rsi):
            if rsi < 30:
                score += 20
            elif rsi > 70:
                score -= 20

        sma_cross = last.get("sma_cross", "NONE")
        if sma_cross == "GOLDEN_CROSS":
            score += 20
        elif sma_cross == "DEATH_CROSS":
            score -= 20

        sma_fast = last.get(f"sma_{config.SMA_FAST}")
        sma_slow = last.get(f"sma_{config.SMA_SLOW}")
        if pd.notna(sma_fast) and pd.notna(sma_slow):
            score += 5 if sma_fast > sma_slow else -5

        macd_cross = last.get("macd_cross", "NONE")
        if macd_cross == "BULLISH":
            score += 15
        elif macd_cross == "BEARISH":
            score -= 15

        bb_pos = last.get("bb_position", "MIDDLE")
        if bb_pos == "BELOW_LOWER":
            score += 10
        elif bb_pos == "ABOVE_UPPER":
            score -= 10

        return max(-100, min(100, score))


if __name__ == "__main__":
    from data_fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    backtester = Backtester(initial_capital=8500)

    print("🧪 Backtest başlıyor...\n")

    tickers_to_test = ["ASELS.IS", "THYAO.IS", "SASA.IS", "GARAN.IS"]

    for ticker in tickers_to_test:
        df = fetcher.fetch_single(ticker, period="1y")
        if df is not None:
            result = backtester.run(ticker, df, verbose=False)
            if result:
                print(result)

                if result.trades:
                    print(f"\n  İşlem Detayları ({ticker}):")
                    for t in result.trades:
                        emoji = "✅" if t.profit_pct > 0 else "❌"
                        print(
                            f"    {emoji} "
                            f"{t.entry_date.strftime('%d.%m')} → "
                            f"{t.exit_date.strftime('%d.%m')} | "
                            f"₺{t.entry_price:.2f} → ₺{t.exit_price:.2f} | "
                            f"{t.profit_pct:+.1f}% | "
                            f"{t.holding_days}g"
                        )


def calculate_metrics(trades, benchmark_return: float = None) -> dict:
    if not trades:
        return {}
    
    winning = [t for t in trades if t.profit_pct > 0]
    losing = [t for t in trades if t.profit_pct <= 0]
    
    avg_win = np.mean([t.profit_pct for t in winning]) if winning else 0
    avg_loss = abs(np.mean([t.profit_pct for t in losing])) if losing else 0
    
    avg_r = avg_win / avg_loss if avg_loss > 0 else 0
    
    return {
        "win_rate": len(winning) / len(trades) * 100 if trades else 0,
        "avg_r": avg_r,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trades": len(trades),
        "benchmark_return": benchmark_return or 0,
    }


def generate_report(result: BacktestResult, benchmark_return: float = None) -> str:
    metrics = calculate_metrics(result.trades, benchmark_return)
    
    bot_return = result.total_return_pct
    alpha = bot_return - (benchmark_return or 0)
    
    emoji = "📈" if alpha >= 0 else "📉"
    
    report = f"""
╔══════════════════════════════════════════╗
║         📊 BACKTEST RAPORU              ║
╠══════════════════════════════════════════╣
  Hisse          : {result.ticker}
  Periyot       : {result.period}
  ─────────────────────────────────────
  Başlangıç      : ₺{result.initial_capital:,.0f}
  Bitiş          : ₺{result.final_capital:,.0f}
  ─────────────────────────────────────
  📊 Bot Getiri  : %{bot_return:+.2f}
  📊 Benchmark   : %{benchmark_return:+.2f}
  {emoji} Alfa       : %{alpha:+.2f}
  ─────────────────────────────────────
  Win Rate      : %{result.win_rate:.1f}
  Ort. R        : {metrics['avg_r']:.2f}
  Ort. Kazanç    : %{metrics['avg_win']:.2f}
  Ort. Kayıp    : %{metrics['avg_loss']:.2f}
  Max Drawdown  : %{result.max_drawdown_pct:.2f}
  Sharpe       : {result.sharpe_ratio:.2f}
╚══════════════════════════════════════════╝
"""
    return report


def compare_benchmark(ticker: str, df: pd.DataFrame) -> float:
    try:
        if yf is None:
            return 0
        bench = yf.download(
            getattr(config, "BENCHMARK_TICKER", "^XU100"),
            start=df.index[0],
            end=df.index[-1],
            progress=False
        )
        if bench is not None and len(bench) > 0:
            bench_cols = [c[0] for c in bench.columns]
            close_col = "Close" if "Close" in bench_cols else bench_cols[0]
            bench_return = (bench[close_col].iloc[-1] / bench[close_col].iloc[0] - 1) * 100
            return bench_return
    except Exception as e:
        logger.warning(f"Benchmark veri hatası: {e}")
    return 0
