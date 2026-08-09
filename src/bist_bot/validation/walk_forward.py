"""Day-based walk-forward validation with out-of-sample metrics and overfitting checks.

WARNING / UYARI
---------------
If you intentionally change default ``train_window`` / ``test_window`` /
``step_size`` (in trading days), the cost defaults (commission/slippage bps),
or the overfitting threshold (``overfitting_return_ratio``), you MUST
consciously update the expected window counts, no-leakage assertions, and
flag triggers in ``tests/test_walk_forward_validation.py``.

This module complements the existing month-based
``bist_bot.backtest.walkforward.WalkForwardValidator`` with a simpler day-based
rolling evaluator that:

1. Splits OHLCV into non-overlapping *or* stepped train/test day windows
2. Runs ``Backtester.run`` on train (in-sample) and test (out-of-sample)
3. Aggregates OOS metrics and compares IS vs OOS for overfitting warnings
4. Always applies transaction costs (commission + slippage bps)

Look-ahead bias rule (enforced):
    ``test.index.min() > train.index.max()`` for every window.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.backtest.engine import Backtester
from bist_bot.backtest.models import BacktestResult, CostModel

logger = get_logger(__name__, component="walk_forward_validation")

# Default windows in *trading days* (approx. 1y train / 1q test / 1q step).
DEFAULT_TRAIN_WINDOW_DAYS = 252
DEFAULT_TEST_WINDOW_DAYS = 63
DEFAULT_STEP_SIZE_DAYS = 63
DEFAULT_COMMISSION_BPS = 2.0
DEFAULT_SLIPPAGE_BPS = 5.0
DEFAULT_OVERFITTING_RETURN_RATIO = 0.5


class BacktesterFactory(Protocol):
    def __call__(
        self,
        *,
        initial_capital: float,
        cost_model: CostModel | None,
        commission_buy_pct: float | None,
        commission_sell_pct: float | None,
        slippage_pct: float | None,
        strategy_params: Any | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class WalkForwardWindowMetrics:
    window_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_rows: int
    test_rows: int
    train_return_pct: float
    test_return_pct: float
    train_max_drawdown_pct: float
    test_max_drawdown_pct: float
    train_sharpe_ratio: float
    test_sharpe_ratio: float
    train_win_rate: float
    test_win_rate: float
    train_trades: int
    test_trades: int
    train_final_capital: float
    test_final_capital: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WalkForwardValidationResult:
    ticker: str
    initial_capital: float
    train_window: int
    test_window: int
    step_size: int
    commission_bps: float
    slippage_bps: float
    windows: list[WalkForwardWindowMetrics] = field(default_factory=list)
    oos_aggregate: dict[str, float] = field(default_factory=dict)
    is_aggregate: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    overfitting_return_ratio: float = DEFAULT_OVERFITTING_RETURN_RATIO

    @property
    def has_overfitting_warning(self) -> bool:
        return "OVERFITTING_WARNING" in self.flags

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "initial_capital": self.initial_capital,
            "train_window": self.train_window,
            "test_window": self.test_window,
            "step_size": self.step_size,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "windows": [window.to_dict() for window in self.windows],
            "oos_aggregate": self.oos_aggregate,
            "is_aggregate": self.is_aggregate,
            "flags": list(self.flags),
            "overfitting_return_ratio": self.overfitting_return_ratio,
            "has_overfitting_warning": self.has_overfitting_warning,
        }


def _empty_metrics() -> dict[str, float]:
    return {
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0,
        "win_rate": 0.0,
        "total_trades": 0.0,
        "final_capital": 0.0,
    }


def _result_metrics(result: BacktestResult | None, initial_capital: float) -> dict[str, float]:
    if result is None:
        metrics = _empty_metrics()
        metrics["final_capital"] = float(initial_capital)
        return metrics
    return {
        "total_return_pct": float(result.total_return_pct),
        "max_drawdown_pct": float(result.max_drawdown_pct),
        "sharpe_ratio": float(result.sharpe_ratio),
        "win_rate": float(result.win_rate),
        "total_trades": float(result.total_trades),
        "final_capital": float(result.final_capital),
    }


def _aggregate(metric_rows: list[dict[str, float]]) -> dict[str, float]:
    if not metric_rows:
        return {
            "count": 0.0,
            "mean_total_return_pct": 0.0,
            "median_total_return_pct": 0.0,
            "std_total_return_pct": 0.0,
            "mean_max_drawdown_pct": 0.0,
            "median_max_drawdown_pct": 0.0,
            "std_max_drawdown_pct": 0.0,
            "mean_sharpe_ratio": 0.0,
            "median_sharpe_ratio": 0.0,
            "std_sharpe_ratio": 0.0,
            "mean_win_rate": 0.0,
            "median_win_rate": 0.0,
            "std_win_rate": 0.0,
            "mean_total_trades": 0.0,
        }

    def _stats(key: str) -> tuple[float, float, float]:
        values = np.asarray([row[key] for row in metric_rows], dtype=float)
        return (
            float(np.mean(values)),
            float(np.median(values)),
            float(np.std(values, ddof=0)),
        )

    ret_mean, ret_med, ret_std = _stats("total_return_pct")
    dd_mean, dd_med, dd_std = _stats("max_drawdown_pct")
    sh_mean, sh_med, sh_std = _stats("sharpe_ratio")
    wr_mean, wr_med, wr_std = _stats("win_rate")
    trades_mean, _, _ = _stats("total_trades")
    return {
        "count": float(len(metric_rows)),
        "mean_total_return_pct": ret_mean,
        "median_total_return_pct": ret_med,
        "std_total_return_pct": ret_std,
        "mean_max_drawdown_pct": dd_mean,
        "median_max_drawdown_pct": dd_med,
        "std_max_drawdown_pct": dd_std,
        "mean_sharpe_ratio": sh_mean,
        "median_sharpe_ratio": sh_med,
        "std_sharpe_ratio": sh_std,
        "mean_win_rate": wr_mean,
        "median_win_rate": wr_med,
        "std_win_rate": wr_std,
        "mean_total_trades": trades_mean,
    }


def _format_ts(value: Any) -> str:
    ts = pd.Timestamp(value)
    return ts.strftime("%Y-%m-%d")


class WalkForwardValidator:
    """Rolling day-window walk-forward evaluator with cost-aware OOS metrics."""

    def __init__(
        self,
        *,
        train_window: int = DEFAULT_TRAIN_WINDOW_DAYS,
        test_window: int = DEFAULT_TEST_WINDOW_DAYS,
        step_size: int = DEFAULT_STEP_SIZE_DAYS,
        commission_bps: float = DEFAULT_COMMISSION_BPS,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
        initial_capital: float = 100_000.0,
        overfitting_return_ratio: float = DEFAULT_OVERFITTING_RETURN_RATIO,
        backtester_factory: BacktesterFactory | None = None,
        use_cost_model: bool = True,
        strategy_params: Any | None = None,
    ) -> None:
        if train_window < 1:
            raise ValueError("train_window must be >= 1")
        if test_window < 1:
            raise ValueError("test_window must be >= 1")
        if step_size < 1:
            raise ValueError("step_size must be >= 1")
        if commission_bps < 0 or slippage_bps < 0:
            raise ValueError("commission_bps and slippage_bps must be >= 0")
        if initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if not (0.0 < overfitting_return_ratio <= 1.0):
            raise ValueError("overfitting_return_ratio must be in (0, 1]")

        self.train_window = int(train_window)
        self.test_window = int(test_window)
        self.step_size = int(step_size)
        self.commission_bps = float(commission_bps)
        self.slippage_bps = float(slippage_bps)
        self.initial_capital = float(initial_capital)
        self.overfitting_return_ratio = float(overfitting_return_ratio)
        self.backtester_factory = backtester_factory
        self.use_cost_model = bool(use_cost_model)
        self.strategy_params = strategy_params

    def build_windows(self, df: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        """Return (train_df, test_df) pairs with no look-ahead leakage."""
        if df is None or df.empty:
            return []
        sorted_df = df.sort_index()
        n = len(sorted_df)
        windows: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        start = 0
        while start + self.train_window + self.test_window <= n:
            train_end = start + self.train_window
            test_end = train_end + self.test_window
            train_df = sorted_df.iloc[start:train_end]
            test_df = sorted_df.iloc[train_end:test_end]
            if train_df.empty or test_df.empty:
                break
            # Hard no-leakage invariant.
            if pd.Timestamp(test_df.index.min()) <= pd.Timestamp(train_df.index.max()):
                raise RuntimeError(
                    "Look-ahead bias detected: test window starts on/before train window ends"
                )
            windows.append((train_df, test_df))
            start += self.step_size
        return windows

    def _make_backtester(self) -> Any:
        commission_pct = self.commission_bps / 10_000.0
        slippage_pct = self.slippage_bps / 10_000.0
        if self.use_cost_model:
            cost_model = CostModel(
                commission_bps=self.commission_bps,
                fixed_slippage_bps=self.slippage_bps,
                slippage_model="fixed",
            )
            commission_buy_pct = None
            commission_sell_pct = None
            slippage_arg = None
        else:
            cost_model = None
            commission_buy_pct = commission_pct
            commission_sell_pct = commission_pct
            slippage_arg = slippage_pct

        if self.backtester_factory is not None:
            return self.backtester_factory(
                initial_capital=self.initial_capital,
                cost_model=cost_model,
                commission_buy_pct=commission_buy_pct,
                commission_sell_pct=commission_sell_pct,
                slippage_pct=slippage_arg,
                strategy_params=self.strategy_params,
            )
        if self.use_cost_model:
            return Backtester(
                initial_capital=self.initial_capital,
                cost_model=cost_model,
                strategy_params=self.strategy_params,
            )
        return Backtester(
            initial_capital=self.initial_capital,
            commission_buy_pct=commission_buy_pct,
            commission_sell_pct=commission_sell_pct,
            slippage_pct=slippage_arg,
            strategy_params=self.strategy_params,
        )

    def run(
        self,
        ticker: str,
        df: pd.DataFrame,
        *,
        tickers: list[str] | None = None,
    ) -> WalkForwardValidationResult | None:
        """Evaluate walk-forward OOS performance for one (or the first of many) tickers.

        ``tickers`` is accepted for API compatibility; when provided without a
        multi-frame mapping, only ``ticker`` + ``df`` are used.
        """
        _ = tickers
        if df is None or df.empty:
            return None

        windows = self.build_windows(df)
        if not windows:
            logger.warning(
                "walk_forward_no_windows",
                ticker=ticker,
                rows=len(df),
                train_window=self.train_window,
                test_window=self.test_window,
            )
            return None

        window_metrics: list[WalkForwardWindowMetrics] = []
        is_rows: list[dict[str, float]] = []
        oos_rows: list[dict[str, float]] = []
        backtester = self._make_backtester()

        for idx, (train_df, test_df) in enumerate(windows, start=1):
            train_result = backtester.run(ticker, train_df, verbose=False)
            test_result = backtester.run(ticker, test_df, verbose=False)
            train_m = _result_metrics(train_result, self.initial_capital)
            test_m = _result_metrics(test_result, self.initial_capital)
            is_rows.append(train_m)
            oos_rows.append(test_m)
            window_metrics.append(
                WalkForwardWindowMetrics(
                    window_index=idx,
                    train_start=_format_ts(train_df.index.min()),
                    train_end=_format_ts(train_df.index.max()),
                    test_start=_format_ts(test_df.index.min()),
                    test_end=_format_ts(test_df.index.max()),
                    train_rows=len(train_df),
                    test_rows=len(test_df),
                    train_return_pct=train_m["total_return_pct"],
                    test_return_pct=test_m["total_return_pct"],
                    train_max_drawdown_pct=train_m["max_drawdown_pct"],
                    test_max_drawdown_pct=test_m["max_drawdown_pct"],
                    train_sharpe_ratio=train_m["sharpe_ratio"],
                    test_sharpe_ratio=test_m["sharpe_ratio"],
                    train_win_rate=train_m["win_rate"],
                    test_win_rate=test_m["win_rate"],
                    train_trades=int(train_m["total_trades"]),
                    test_trades=int(test_m["total_trades"]),
                    train_final_capital=train_m["final_capital"],
                    test_final_capital=test_m["final_capital"],
                )
            )

        is_aggregate = _aggregate(is_rows)
        oos_aggregate = _aggregate(oos_rows)
        flags: list[str] = []

        # Overfitting: mean OOS return is much worse than mean IS return.
        is_ret = is_aggregate["mean_total_return_pct"]
        oos_ret = oos_aggregate["mean_total_return_pct"]
        if is_ret > 0 and oos_ret < is_ret * self.overfitting_return_ratio:
            flags.append("OVERFITTING_WARNING")
            logger.warning(
                "walk_forward_overfitting_warning",
                ticker=ticker,
                is_mean_return=is_ret,
                oos_mean_return=oos_ret,
                ratio=self.overfitting_return_ratio,
            )
        # Also flag if IS is strongly positive while OOS is negative.
        if is_ret >= 5.0 and oos_ret < 0.0 and "OVERFITTING_WARNING" not in flags:
            flags.append("OVERFITTING_WARNING")

        return WalkForwardValidationResult(
            ticker=ticker,
            initial_capital=self.initial_capital,
            train_window=self.train_window,
            test_window=self.test_window,
            step_size=self.step_size,
            commission_bps=self.commission_bps,
            slippage_bps=self.slippage_bps,
            windows=window_metrics,
            oos_aggregate=oos_aggregate,
            is_aggregate=is_aggregate,
            flags=flags,
            overfitting_return_ratio=self.overfitting_return_ratio,
        )


__all__ = [
    "DEFAULT_COMMISSION_BPS",
    "DEFAULT_OVERFITTING_RETURN_RATIO",
    "DEFAULT_SLIPPAGE_BPS",
    "DEFAULT_STEP_SIZE_DAYS",
    "DEFAULT_TEST_WINDOW_DAYS",
    "DEFAULT_TRAIN_WINDOW_DAYS",
    "WalkForwardValidationResult",
    "WalkForwardValidator",
    "WalkForwardWindowMetrics",
]
