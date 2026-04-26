"""Correlation cache and portfolio correlation helpers."""

from __future__ import annotations

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.risk.models import RiskLevels
from bist_bot.risk.sizing import apply_position_budget

logger = get_logger(__name__, component="risk_correlation")


def build_global_correlation_cache(data: dict) -> pd.DataFrame | None:
    closes = {}
    for ticker, df_or_dict in data.items():
        if isinstance(df_or_dict, dict) and "trend" in df_or_dict:
            df = df_or_dict["trend"]
        else:
            df = df_or_dict
        if df is not None and not df.empty and "close" in df.columns:
            closes[ticker] = df["close"].astype(float).rename(ticker)

    if closes:
        close_frame = pd.concat(closes.values(), axis=1, join="inner").dropna()
        if not close_frame.empty:
            cache = close_frame.pct_change().dropna().corr()
            logger.info("correlation_cache_ready", matrix_shape=str(cache.shape))
            return cache
    return None


def get_correlation_matrix(portfolio_history: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if not portfolio_history:
        return pd.DataFrame()
    series_map = {
        ticker: history["close"].astype(float).rename(ticker)
        for ticker, history in portfolio_history.items()
        if history is not None and not history.empty and "close" in history.columns
    }
    if not series_map:
        return pd.DataFrame()
    close_frame = pd.concat(series_map.values(), axis=1, join="inner").dropna()
    if close_frame.empty or close_frame.shape[1] < 2:
        return pd.DataFrame(index=close_frame.columns, columns=close_frame.columns)
    returns = close_frame.pct_change().dropna()
    if returns.empty:
        return pd.DataFrame(index=close_frame.columns, columns=close_frame.columns)
    return returns.corr()


def get_correlated_positions(
    ticker: str,
    candidate_df: pd.DataFrame,
    portfolio_history: dict[str, pd.DataFrame],
    global_corr_cache: pd.DataFrame | None,
    correlation_threshold: float,
) -> list[str]:
    if not portfolio_history:
        return []
    correlated: list[str] = []

    if global_corr_cache is not None and ticker in global_corr_cache.columns:
        for existing_ticker in portfolio_history:
            if existing_ticker in global_corr_cache.columns:
                corr = global_corr_cache.loc[ticker, existing_ticker]
                if pd.notna(corr) and abs(float(corr)) >= correlation_threshold:
                    correlated.append(existing_ticker)
        return correlated

    candidate_close = candidate_df[["close"]].rename(columns={"close": ticker}).astype(float)
    for existing_ticker, history in portfolio_history.items():
        existing_close = history[["close"]].rename(columns={"close": existing_ticker}).astype(float)
        aligned = pd.concat([candidate_close, existing_close], axis=1, join="inner").dropna()
        if aligned.empty or len(aligned) < 10:
            continue
        corr = aligned.pct_change().dropna().corr().iloc[0, 1]
        if pd.notna(corr) and abs(float(corr)) >= correlation_threshold:
            correlated.append(existing_ticker)
    return correlated


def apply_portfolio_risk(
    ticker: str,
    df: pd.DataFrame,
    levels: RiskLevels,
    portfolio_history: dict[str, pd.DataFrame],
    global_corr_cache: pd.DataFrame | None,
    correlation_threshold: float,
    correlation_max_cluster: int,
    correlation_min_scale: float,
    correlation_risk_step: float,
    capital: float,
    max_risk_pct: float,
) -> RiskLevels:
    correlated = get_correlated_positions(
        ticker, df, portfolio_history, global_corr_cache, correlation_threshold
    )
    levels.correlated_tickers = correlated

    if len(correlated) > correlation_max_cluster:
        levels.blocked_by_correlation = True
        levels.correlation_scale = 0.0
        levels.position_size = 0
        levels.max_loss_tl = 0.0
        levels.risk_budget_tl = 0.0
        logger.warning(
            "correlation_limit_applied", ticker=ticker, correlated_tickers=", ".join(correlated)
        )
        return levels

    correlation_scale = max(correlation_min_scale, 1.0 - (len(correlated) * correlation_risk_step))
    levels.correlation_scale = round(correlation_scale, 2)
    apply_position_budget(float(df["close"].iloc[-1]), levels, capital, max_risk_pct)
    return levels
