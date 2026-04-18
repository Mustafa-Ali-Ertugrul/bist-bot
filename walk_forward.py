import logging
from typing import Optional
import pandas as pd
from dataclasses import dataclass

from config import settings
from data_fetcher import BISTDataFetcher
from backtest import Backtester

logger = logging.getLogger(__name__)


@dataclass
class OptimizedParams:
    rsi_oversold: int
    buy_threshold: int
    sell_threshold: int
    total_return: float
    win_rate: float


class OptimizingBacktester(Backtester):
    def __init__(self, *args, rsi_oversold: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.rsi_oversold = rsi_oversold

    def _calculate_score(self, df: pd.DataFrame) -> float:
        score = super()._calculate_score(df)
        if len(df) < 2:
            return score

        last = df.iloc[-1]
        rsi = last.get("rsi")
        if pd.notna(rsi):
            if settings.RSI_OVERSOLD <= rsi < settings.RSI_OVERBOUGHT and rsi < self.rsi_oversold:
                score += 20
            elif self.rsi_oversold <= rsi < settings.RSI_OVERSOLD:
                score -= 20
        return max(-100.0, min(100.0, score))


def find_best_params(
    ticker: str,
    df: pd.DataFrame,
    rsi_range: tuple = (25, 35),
    lookback_days: int = None,
    test_days: int = None,
) -> Optional[OptimizedParams]:
    lookback_days = lookback_days or settings.WALKFORWARD_TRAIN_DAYS
    test_days = test_days or settings.WALKFORWARD_TEST_DAYS
    if df is None or len(df) < lookback_days + 30:
        logger.warning(f"Yetersiz veri: {len(df) if df is not None else 0}")
        return None

    df = df.tail(lookback_days + 30)
    split_idx = len(df) - 30

    train_df = df.iloc[:split_idx]
    df.iloc[split_idx:]

    best_params = None
    best_return = float("-inf")

    for rsi_oversold in range(rsi_range[0], rsi_range[1] + 1, 1):
        bt = OptimizingBacktester(
            initial_capital=settings.INITIAL_CAPITAL,
            buy_threshold=35,
            sell_threshold=-15,
            rsi_oversold=rsi_oversold,
        )

        result = bt.run(ticker, train_df, verbose=False)

        if result and result.total_return_pct > best_return:
            best_return = result.total_return_pct
            best_params = OptimizedParams(
                rsi_oversold=rsi_oversold,
                buy_threshold=35,
                sell_threshold=-15,
                total_return=result.total_return_pct,
                win_rate=result.win_rate,
            )

    if best_params:
        logger.info(
            f"  {ticker}: En iyi RSI={best_params.rsi_oversold} "
            f"(train return: %{best_params.total_return:.1f})"
        )

    return best_params


def walk_forward_batch(
    tickers: list = None,
    rsi_range: tuple = (25, 35),
    lookback_days: int = 180,
) -> dict:
    tickers = tickers or settings.WATCHLIST[:10]
    fetcher = BISTDataFetcher()
    results = {}

    for ticker in tickers:
        logger.info(f"  Optimize: {ticker}")
        df = fetcher.fetch_single(ticker, period="1y")
        if df is not None:
            params = find_best_params(ticker, df, rsi_range, lookback_days)
            if params:
                results[ticker] = params

    return results


def apply_optimized_params(ticker: str, params: OptimizedParams) -> bool:
    logger.info(
        f"  {ticker}: Önerilen RSI eşiği {params.rsi_oversold}"
    )
    return True
