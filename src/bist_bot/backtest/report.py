import importlib
from typing import cast

import numpy as np
import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.contracts import StrategyEngineProtocol

try:
    import yfinance as yf
except ImportError:
    yf = None

from bist_bot import strategy as strategy_module

from .models import BacktestResult
from .strategy import StrategyBacktester

logger = get_logger(__name__, component="backtest")


def _reload_strategy_dependencies() -> StrategyEngineProtocol:
    reloaded_module = importlib.reload(strategy_module)
    return cast(StrategyEngineProtocol, reloaded_module.StrategyEngine())


if __name__ == "__main__":
    from bist_bot.data.fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    backtester = StrategyBacktester(
        initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0),
        engine=_reload_strategy_dependencies(),
    )

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
                            f"    {emoji} {t.entry_date.strftime('%d.%m')} → {t.exit_date.strftime('%d.%m')} | "
                            f"₺{t.entry_price:.2f} → ₺{t.exit_price:.2f} | {t.profit_pct:+.1f}% | {t.holding_days}g"
                        )


def calculate_metrics(trades, benchmark_return: float | None = None) -> dict:
    if not trades:
        return {}

    winning = [t for t in trades if t.profit_pct > 0]
    losing = [t for t in trades if t.profit_pct <= 0]

    avg_win = float(np.mean([t.profit_pct for t in winning])) if winning else 0.0
    avg_loss = abs(float(np.mean([t.profit_pct for t in losing]))) if losing else 0.0
    avg_r = avg_win / avg_loss if avg_loss > 0 else 0.0

    return {
        "win_rate": len(winning) / len(trades) * 100 if trades else 0,
        "avg_r": avg_r,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trades": len(trades),
        "benchmark_return": benchmark_return or 0,
    }


def generate_report(result: BacktestResult, benchmark_return: float | None = None) -> str:
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
  📊 Benchmark   : %{(benchmark_return or 0):+.2f}
  {emoji} Alfa       : %{alpha:+.2f}
  ─────────────────────────────────────
  Win Rate      : %{result.win_rate:.1f}
  Ort. R        : {metrics["avg_r"]:.2f}
  Ort. Kazanç    : %{metrics["avg_win"]:.2f}
  Ort. Kayıp    : %{metrics["avg_loss"]:.2f}
  Max Drawdown  : %{result.max_drawdown_pct:.2f}
  Sharpe       : {result.sharpe_ratio:.2f}
╚══════════════════════════════════════════╝
"""
    return report


def compare_benchmark(_ticker: str, df: pd.DataFrame) -> float:
    try:
        if yf is None:
            return 0.0
        bench = yf.download(
            getattr(settings, "BENCHMARK_TICKER", "^XU100"),
            start=df.index[0],
            end=df.index[-1],
            progress=False,
        )
        if bench is not None and len(bench) > 0:
            bench_cols = [c[0] if isinstance(c, tuple) else c for c in bench.columns]
            close_col = "Close" if "Close" in bench_cols else bench_cols[0]
            close_series = bench[close_col]
            return float((close_series.iloc[-1] / close_series.iloc[0] - 1) * 100)
    except Exception as e:
        logger.warning("benchmark_data_error", error=str(e))
    return 0.0
