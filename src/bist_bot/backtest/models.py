import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

import numpy as np
import pandas as pd

try:
    from sklearn.metrics import log_loss, roc_auc_score
except ImportError:
    log_loss = None
    roc_auc_score = None


class IntrabarExit(TypedDict):
    reason: str
    reference_price: float


class SignalBuilder(Protocol):
    def __call__(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]: ...


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
    exit_reason: str = ""
    gross_profit_tl: float = 0.0
    entry_notional_tl: float = 0.0
    total_cost_tl: float = 0.0
    commission_tl: float = 0.0
    bsmv_tl: float = 0.0
    exchange_fee_tl: float = 0.0
    slippage_tl: float = 0.0
    signal_probability: float | None = None
    position_fraction: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_date": self.entry_date.isoformat(),
            "exit_date": self.exit_date.isoformat(),
            "ticker": self.ticker,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "signal_score": self.signal_score,
            "profit_pct": self.profit_pct,
            "profit_tl": self.profit_tl,
            "holding_days": self.holding_days,
            "exit_reason": self.exit_reason,
            "gross_profit_tl": self.gross_profit_tl,
            "entry_notional_tl": self.entry_notional_tl,
            "total_cost_tl": self.total_cost_tl,
            "commission_tl": self.commission_tl,
            "bsmv_tl": self.bsmv_tl,
            "exchange_fee_tl": self.exchange_fee_tl,
            "slippage_tl": self.slippage_tl,
            "signal_probability": self.signal_probability,
            "position_fraction": self.position_fraction,
        }


@dataclass
class CostBreakdown:
    gross_return: float = 0.0
    total_commission: float = 0.0
    total_bsmv: float = 0.0
    total_exchange_fee: float = 0.0
    total_slippage: float = 0.0
    net_return: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "gross_return": self.gross_return,
            "total_commission": self.total_commission,
            "total_bsmv": self.total_bsmv,
            "total_exchange_fee": self.total_exchange_fee,
            "total_slippage": self.total_slippage,
            "net_return": self.net_return,
        }


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 2.0
    bsmv_bps: float = 0.1
    exchange_fee_bps: float = 0.3
    slippage_model: str = "fixed"
    fixed_slippage_bps: float = 5.0
    volume_slippage_bps_per_volume_ratio: float = 200.0
    atr_slippage_ratio: float = 0.10
    max_slippage_bps: float = 50.0


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
    sortino_ratio: float = 0.0
    cagr: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pct: float = 0.0
    exposure_pct: float = 0.0
    turnover_ratio: float = 0.0
    tail_loss_pct: float = 0.0
    longest_loss_streak: int = 0
    probability_diagnostics: dict[str, Any] = field(default_factory=dict)
    mode: str = "base_fixed_size"
    universe_as_of: str | None = None
    cost_breakdown: CostBreakdown = field(default_factory=CostBreakdown)
    trades: list[BacktestTrade] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "period": self.period,
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_return_pct": self.total_return_pct,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "avg_profit_pct": self.avg_profit_pct,
            "avg_loss_pct": self.avg_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "cagr": self.cagr,
            "calmar_ratio": self.calmar_ratio,
            "profit_factor": self.profit_factor,
            "avg_trade_pct": self.avg_trade_pct,
            "exposure_pct": self.exposure_pct,
            "turnover_ratio": self.turnover_ratio,
            "tail_loss_pct": self.tail_loss_pct,
            "longest_loss_streak": self.longest_loss_streak,
            "probability_diagnostics": self.probability_diagnostics,
            "mode": self.mode,
            "universe_as_of": self.universe_as_of,
            "cost_breakdown": self.cost_breakdown.to_dict(),
            "trades": [trade.to_dict() for trade in self.trades],
        }

    def to_json(self, output_path: str | Path | None = None) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        return payload

    def __str__(self):
        return (
            f"\n{'═' * 55}\n"
            f"📊 BACKTEST SONUCU: {self.ticker}\n"
            f"{'═' * 55}\n"
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
            f"  Sortino Ratio   : {self.sortino_ratio:.2f}\n"
            f"  Calmar Ratio    : {self.calmar_ratio:.2f}\n"
            f"  Profit Factor   : {self.profit_factor:.2f}\n"
            f"{'═' * 55}"
        )


@dataclass(frozen=True)
class VectorizedSignals:
    dates: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    enter_signals: np.ndarray
    exit_signals: np.ndarray
    scores: np.ndarray
    stop_losses: np.ndarray
    target_prices: np.ndarray


class WindowMode(str, Enum):
    ROLLING = "rolling"
    ANCHORED = "anchored"


class BacktestMode(str, Enum):
    BASE_FIXED_SIZE = "base_fixed_size"
    META_FILTER_FIXED_SIZE = "meta_filter_fixed_size"
    META_FILTER_FRACTIONAL_KELLY = "meta_filter_fractional_kelly"


@dataclass
class AblationComparison:
    base_metric: float
    candidate_metric: float
    delta: float


@dataclass
class BacktestAblationResult:
    ticker: str
    runs: dict[str, BacktestResult]
    comparisons: dict[str, dict[str, AblationComparison]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "runs": {name: result.to_dict() for name, result in self.runs.items()},
            "comparisons": {
                run_name: {
                    metric: {
                        "base_metric": comparison.base_metric,
                        "candidate_metric": comparison.candidate_metric,
                        "delta": comparison.delta,
                    }
                    for metric, comparison in metrics.items()
                }
                for run_name, metrics in self.comparisons.items()
            },
        }


@dataclass
class WalkForwardWindowResult:
    window_index: int
    train_period: str
    test_period: str
    train_rows: int
    test_rows: int
    params: dict[str, Any]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_index": self.window_index,
            "train_period": self.train_period,
            "test_period": self.test_period,
            "train_rows": self.train_rows,
            "test_rows": self.test_rows,
            "params": self.params,
            "metrics": self.metrics,
        }


@dataclass
class WalkForwardResult:
    ticker: str
    initial_capital: float
    final_capital: float
    train_window_months: int
    test_window_months: int
    step_months: int
    mode: str
    universe_as_of: str | None
    windows: list[WalkForwardWindowResult]
    combined_metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "train_window_months": self.train_window_months,
            "test_window_months": self.test_window_months,
            "step_months": self.step_months,
            "mode": self.mode,
            "window_count": len(self.windows),
            "universe_as_of": self.universe_as_of,
            "combined_metrics": self.combined_metrics,
            "windows": [window.to_dict() for window in self.windows],
        }

    def to_json(self, output_path: str | Path | None = None) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        return payload


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, (pd.Series, pd.DataFrame, np.ndarray, list, tuple, pd.Index)):
            return default
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    timestamp = pd.Timestamp(value)
    return cast(datetime, timestamp.to_pydatetime())


def _annualized_ratios(returns: np.ndarray) -> tuple[float, float]:
    if returns.size <= 1:
        return 0.0, 0.0

    mean_return = float(np.mean(returns))
    std_return = float(np.std(returns))
    sharpe = float(mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0.0

    downside = returns[returns < 0]
    downside_std = float(np.std(downside)) if downside.size > 0 else 0.0
    sortino = float(mean_return / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0
    return sharpe, sortino


def _calculate_cagr(
    initial_capital: float,
    final_capital: float,
    start_date: datetime,
    end_date: datetime,
) -> float:
    total_days = max((end_date - start_date).days, 0)
    if total_days <= 0 or initial_capital <= 0 or final_capital <= 0:
        return 0.0
    years = total_days / 365.25
    if years <= 0:
        return 0.0
    return float((final_capital / initial_capital) ** (1 / years) - 1)


def _longest_loss_streak(trades: list[BacktestTrade]) -> int:
    streak = 0
    longest = 0
    for trade in trades:
        if trade.profit_pct <= 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return longest


def _probability_diagnostics(trades: list[BacktestTrade]) -> dict[str, Any]:
    probability_trades = [trade for trade in trades if trade.signal_probability is not None]
    if not probability_trades:
        return {}

    probabilities = np.clip(
        np.array(
            [cast(float, trade.signal_probability) for trade in probability_trades],
            dtype=float,
        ),
        1e-6,
        1.0 - 1e-6,
    )
    labels = np.array([1 if trade.profit_pct > 0 else 0 for trade in probability_trades], dtype=int)
    diagnostics: dict[str, Any] = {
        "count": len(probability_trades),
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 4),
    }
    if log_loss is not None:
        diagnostics["log_loss"] = round(float(log_loss(labels, probabilities, labels=[0, 1])), 4)
    if roc_auc_score is not None and len(np.unique(labels)) > 1:
        diagnostics["roc_auc"] = round(float(roc_auc_score(labels, probabilities)), 4)

    threshold_rows = []
    for threshold in [0.50, 0.55, 0.60, 0.65]:
        predicted_positive = probabilities >= threshold
        tp = int(np.sum(predicted_positive & (labels == 1)))
        fp = int(np.sum(predicted_positive & (labels == 0)))
        fn = int(np.sum((~predicted_positive) & (labels == 1)))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        threshold_rows.append(
            {
                "threshold": threshold,
                "precision": round(float(precision), 4),
                "recall": round(float(recall), 4),
                "support": int(np.sum(predicted_positive)),
            }
        )
    diagnostics["precision_recall_by_threshold"] = threshold_rows

    bucket_rows: list[dict[str, Any]] = []
    for low, high in [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)]:
        mask = (probabilities >= low) & (probabilities < high)
        if not np.any(mask):
            bucket_rows.append(
                {
                    "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
                    "count": 0,
                    "avg_probability": 0.0,
                    "realized_win_rate": 0.0,
                    "avg_profit_pct": 0.0,
                }
            )
            continue
        bucket_trade_returns = np.array(
            [trade.profit_pct for idx, trade in enumerate(probability_trades) if mask[idx]],
            dtype=float,
        )
        bucket_rows.append(
            {
                "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
                "count": int(mask.sum()),
                "avg_probability": round(float(np.mean(probabilities[mask])), 4),
                "realized_win_rate": round(float(np.mean(labels[mask])), 4),
                "avg_profit_pct": round(float(np.mean(bucket_trade_returns)), 4),
            }
        )
    diagnostics["probability_buckets"] = bucket_rows
    diagnostics["calibration_curve"] = [
        {
            "bucket": row["bucket"],
            "predicted": row["avg_probability"],
            "observed": row["realized_win_rate"],
        }
        for row in bucket_rows
        if row["count"] > 0
    ]
    return diagnostics


def _build_cost_breakdown(
    initial_capital: float, final_capital: float, trades: list[BacktestTrade]
) -> CostBreakdown:
    total_commission = sum(trade.commission_tl for trade in trades)
    total_bsmv = sum(trade.bsmv_tl for trade in trades)
    total_exchange_fee = sum(trade.exchange_fee_tl for trade in trades)
    total_slippage = sum(trade.slippage_tl for trade in trades)
    gross_return = sum(trade.gross_profit_tl for trade in trades)
    net_return = final_capital - initial_capital

    return CostBreakdown(
        gross_return=round(gross_return, 2),
        total_commission=round(total_commission, 2),
        total_bsmv=round(total_bsmv, 2),
        total_exchange_fee=round(total_exchange_fee, 2),
        total_slippage=round(total_slippage, 2),
        net_return=round(net_return, 2),
    )


def _summarize_trades_and_equity(
    ticker: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    final_capital: float,
    trades: list[BacktestTrade],
    equity_history: list[float],
) -> dict[str, Any]:
    total_return_pct = (
        (final_capital - initial_capital) / initial_capital * 100 if initial_capital else 0.0
    )
    winning = [trade for trade in trades if trade.profit_pct > 0]
    losing = [trade for trade in trades if trade.profit_pct <= 0]

    cap_series = pd.Series(equity_history, dtype=float)
    rolling_max = cap_series.cummax()
    drawdown = (cap_series - rolling_max) / rolling_max * 100
    max_drawdown_pct = float(drawdown.min()) if not drawdown.empty else 0.0

    returns = np.array([trade.profit_pct for trade in trades], dtype=float)
    sharpe_ratio, sortino_ratio = _annualized_ratios(returns)
    avg_trade_pct = float(np.mean(returns)) if returns.size else 0.0
    gross_profit = sum(trade.profit_tl for trade in winning)
    gross_loss = abs(sum(trade.profit_tl for trade in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    cagr = _calculate_cagr(initial_capital, final_capital, start_date, end_date)
    calmar_ratio = cagr / abs(max_drawdown_pct / 100) if max_drawdown_pct < 0 else 0.0
    total_days = max((_to_datetime(end_date) - _to_datetime(start_date)).days, 1)
    total_holding_days = sum(trade.holding_days for trade in trades)
    exposure_pct = min(100.0, total_holding_days / total_days * 100)
    turnover_ratio = (
        sum(trade.entry_notional_tl for trade in trades) / initial_capital
        if initial_capital > 0
        else 0.0
    )
    tail_loss_pct = float(np.percentile(returns, 5)) if returns.size else 0.0
    probability_diagnostics = _probability_diagnostics(trades)

    return {
        "ticker": ticker,
        "period": f"{start_date.strftime('%d.%m.%Y')} → {end_date.strftime('%d.%m.%Y')}",
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": round(len(winning) / len(trades) * 100, 1) if trades else 0.0,
        "avg_profit_pct": round(float(np.mean([trade.profit_pct for trade in winning])), 2)
        if winning
        else 0.0,
        "avg_loss_pct": round(float(np.mean([trade.profit_pct for trade in losing])), 2)
        if losing
        else 0.0,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "sortino_ratio": round(sortino_ratio, 2),
        "cagr": round(cagr * 100, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_trade_pct": round(avg_trade_pct, 2),
        "exposure_pct": round(exposure_pct, 2),
        "turnover_ratio": round(turnover_ratio, 2),
        "tail_loss_pct": round(tail_loss_pct, 2),
        "longest_loss_streak": _longest_loss_streak(trades),
        "probability_diagnostics": probability_diagnostics,
        "cost_breakdown": _build_cost_breakdown(initial_capital, final_capital, trades),
    }
