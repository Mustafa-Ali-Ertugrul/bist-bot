import logging
from typing import Optional
import pandas as pd
import numpy as np
from dataclasses import dataclass

import config
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


def find_best_params(
    ticker: str,
    df: pd.DataFrame,
    rsi_range: tuple = (25, 35),
    lookback_days: int = None,
    test_days: int = None,
) -> Optional[OptimizedParams]:
    lookback_days = lookback_days or getattr(config, "WALKFORWARD_TRAIN_DAYS", 180)
    test_days = test_days or getattr(config, "WALKFORWARD_TEST_DAYS", 30)
    if df is None or len(df) < lookback_days + 30:
        logger.warning(f"Yetersiz veri: {len(df) if df is not None else 0}")
        return None

    df = df.tail(lookback_days + 30)
    split_idx = len(df) - 30

    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    best_params = None
    best_return = float("-inf")

    for rsi_oversold in range(rsi_range[0], rsi_range[1] + 1, 1):
        original_rsi = config.RSI_OVERSOLD
        config.RSI_OVERSOLD = rsi_oversold

        bt = Backtester(
            initial_capital=getattr(config, "INITIAL_CAPITAL", 8500.0),
            buy_threshold=35,
            sell_threshold=-15,
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

        config.RSI_OVERSOLD = original_rsi

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
    tickers = tickers or config.WATCHLIST[:10]
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
    config.RSI_OVERSOLD = params.rsi_oversold
    logger.info(
        f"  {ticker}: RSI eşiği {config.RSI_OVERSOLD} olarak ayarlandı"
    )
    return True
