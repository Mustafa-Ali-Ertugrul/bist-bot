import json
import importlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, TypedDict, cast

import numpy as np
import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.ml.features import build_feature_payload
from bist_bot.risk.sizing import calculate_kelly_fraction

try:
    import yfinance as yf
except ImportError:
    yf = None

from bist_bot import strategy as strategy_module
from bist_bot.contracts import StrategyEngineProtocol
from bist_bot.indicators import TechnicalIndicators
from bist_bot.strategy.signal_models import SignalType

try:  # pragma: no cover - optional dependency behavior
    from sklearn.metrics import log_loss, roc_auc_score  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    log_loss = None
    roc_auc_score = None

logger = get_logger(__name__, component="backtest")


class IntrabarExit(TypedDict):
    reason: str
    reference_price: float


class SignalBuilder(Protocol):
    def __call__(
        self, ticker: str, history: pd.DataFrame
    ) -> dict[str, float | bool]: ...


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
        if isinstance(
            value, (pd.Series, pd.DataFrame, np.ndarray, list, tuple, pd.Index)
        ):
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
    sortino = (
        float(mean_return / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0
    )
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
    probability_trades = [
        trade for trade in trades if trade.signal_probability is not None
    ]
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
    labels = np.array(
        [1 if trade.profit_pct > 0 else 0 for trade in probability_trades], dtype=int
    )
    diagnostics: dict[str, Any] = {
        "count": int(len(probability_trades)),
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 4),
    }
    if log_loss is not None:
        diagnostics["log_loss"] = round(
            float(log_loss(labels, probabilities, labels=[0, 1])), 4
        )
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
            [
                trade.profit_pct
                for idx, trade in enumerate(probability_trades)
                if mask[idx]
            ],
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
        (final_capital - initial_capital) / initial_capital * 100
        if initial_capital
        else 0.0
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
        "avg_profit_pct": round(
            float(np.mean([trade.profit_pct for trade in winning])), 2
        )
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


class Backtester:
    def __init__(
        self,
        initial_capital: Optional[float] = None,
        commission_buy_pct: Optional[float] = None,
        commission_sell_pct: Optional[float] = None,
        buy_threshold: Optional[float] = None,
        sell_threshold: Optional[float] = None,
        slippage_pct: Optional[float] = None,
        target_rr: float = 2.0,
        indicators: Optional[TechnicalIndicators] = None,
        cost_model: Optional[CostModel] = None,
        meta_model: Any | None = None,
        mode: BacktestMode | str = BacktestMode.BASE_FIXED_SIZE,
        min_probability: float | None = None,
        fractional_kelly: float | None = None,
        max_position_cap_pct: float | None = None,
    ):
        self.initial_capital = float(
            initial_capital
            if initial_capital is not None
            else getattr(settings, "INITIAL_CAPITAL", 8500.0)
        )
        default_commission = float(getattr(settings, "BACKTEST_COMMISSION_PCT", 0.001))
        self.commission_buy_pct = float(
            commission_buy_pct
            if commission_buy_pct is not None
            else getattr(settings, "BACKTEST_COMMISSION_BUY_PCT", default_commission)
        )
        self.commission_sell_pct = float(
            commission_sell_pct
            if commission_sell_pct is not None
            else getattr(settings, "BACKTEST_COMMISSION_SELL_PCT", default_commission)
        )
        self.slippage_pct = float(
            slippage_pct
            if slippage_pct is not None
            else getattr(settings, "BACKTEST_SLIPPAGE_PCT", 0.0005)
        )
        use_legacy_costs = (
            any(
                value is not None
                for value in (commission_buy_pct, commission_sell_pct, slippage_pct)
            )
            and cost_model is None
        )
        self.cost_model = None if use_legacy_costs else (cost_model or CostModel())
        self.buy_threshold = float(
            buy_threshold if buy_threshold is not None else settings.BUY_THRESHOLD
        )
        self.sell_threshold = float(
            sell_threshold if sell_threshold is not None else settings.SELL_THRESHOLD
        )
        self.target_rr = float(target_rr)
        self.indicators = indicators or TechnicalIndicators()
        self.avg_holding_days = 0.0
        self.signal_builder: Optional[SignalBuilder] = None
        self.meta_model = meta_model
        self.mode = BacktestMode(mode)
        self.min_probability = float(
            min_probability
            if min_probability is not None
            else getattr(settings, "MIN_SIGNAL_PROBABILITY", 0.5)
        )
        self.fractional_kelly = float(
            fractional_kelly
            if fractional_kelly is not None
            else getattr(settings, "KELLY_FRACTION_SCALE", 0.25)
        )
        self.max_position_cap_pct = float(
            max_position_cap_pct
            if max_position_cap_pct is not None
            else getattr(settings, "MAX_POSITION_CAP_PCT", 90.0)
        )

    def _precalculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Precompute default backtest signals in a vectorized form.

        Aligned with ``strategy.scoring`` / ``StrategyParams`` weights so that
        the default vectorized backtest path produces scores comparable to the
        live ``StrategyEngine``.
        """
        from bist_bot.strategy.params import StrategyParams

        df = df.copy()
        p = StrategyParams()
        score = np.zeros(len(df), dtype=float)

        # ── Momentum ──────────────────────────────────────────────────
        if "rsi" in df.columns:
            rsi = cast(pd.Series, df["rsi"]).to_numpy(dtype=float)
            score += np.where(rsi < p.rsi_oversold_extreme, p.score_rsi_extreme, 0.0)
            score += np.where(
                (rsi >= p.rsi_oversold_extreme) & (rsi < p.rsi_oversold),
                p.score_rsi_normal,
                0.0,
            )
            score += np.where(
                (rsi >= p.rsi_oversold) & (rsi < p.rsi_neutral_low),
                p.score_rsi_weak_low,
                0.0,
            )
            score -= np.where(rsi > p.rsi_overbought_extreme, p.score_rsi_extreme, 0.0)
            score -= np.where(
                (rsi <= p.rsi_overbought_extreme) & (rsi > p.rsi_overbought),
                p.score_rsi_normal,
                0.0,
            )
            score -= np.where(
                (rsi <= p.rsi_overbought) & (rsi > p.rsi_neutral_high),
                p.score_rsi_weak_high,
                0.0,
            )

        if "stoch_k" in df.columns and "stoch_d" in df.columns:
            sk = cast(pd.Series, df["stoch_k"]).to_numpy(dtype=float)
            sd = cast(pd.Series, df["stoch_d"]).to_numpy(dtype=float)
            if "stoch_cross" in df.columns:
                sc = cast(pd.Series, df["stoch_cross"]).astype(str).to_numpy()
                score += np.where(sc == "BULLISH", p.score_stoch_cross, 0.0)
                score -= np.where(sc == "BEARISH", p.score_stoch_cross, 0.0)
            score += np.where(
                np.isnan(sk) | np.isnan(sd),
                0.0,
                np.where((sk < 20) & (sd < 20), p.score_stoch_extreme, 0.0),
            )
            score -= np.where(
                np.isnan(sk) | np.isnan(sd),
                0.0,
                np.where((sk > 80) & (sd > 80), p.score_stoch_extreme, 0.0),
            )
            score += np.where(
                np.isnan(sk) | np.isnan(sd),
                0.0,
                np.where((sk > sd) & (sk < 50), p.score_stoch_trend, 0.0),
            )
            score -= np.where(
                np.isnan(sk) | np.isnan(sd),
                0.0,
                np.where((sk < sd) & (sk > 50), p.score_stoch_trend, 0.0),
            )

        if "cci" in df.columns:
            cci = cast(pd.Series, df["cci"]).to_numpy(dtype=float)
            score += np.where(cci < -100, p.score_cci_extreme, 0.0)
            score += np.where((cci >= -100) & (cci < -50), p.score_cci_normal, 0.0)
            score -= np.where(cci > 100, p.score_cci_extreme, 0.0)
            score -= np.where((cci <= 100) & (cci > 50), p.score_cci_normal, 0.0)

        # ── Trend ─────────────────────────────────────────────────────
        ema_long_col = f"ema_{settings.EMA_LONG}"
        if ema_long_col in df.columns:
            price = df["close"].to_numpy(dtype=float)
            ema_long = cast(pd.Series, df[ema_long_col]).to_numpy(dtype=float)
            above = ~np.isnan(ema_long) & (price > ema_long)
            score += np.where(above, p.score_ema_cross, 0.0)
            score -= np.where(~above & ~np.isnan(ema_long), p.score_ema_cross, 0.0)

        if "sma_cross" in df.columns:
            sma_cross = cast(pd.Series, df["sma_cross"]).astype(str).to_numpy()
            score += np.where(
                sma_cross == "GOLDEN_CROSS", p.score_sma_golden_cross, 0.0
            )
            score -= np.where(sma_cross == "DEATH_CROSS", p.score_sma_golden_cross, 0.0)
        else:
            sma_fast_col = f"sma_{settings.SMA_FAST}"
            sma_slow_col = f"sma_{settings.SMA_SLOW}"
            if sma_fast_col in df.columns and sma_slow_col in df.columns:
                sma_fast = cast(pd.Series, df[sma_fast_col]).to_numpy(dtype=float)
                sma_slow = cast(pd.Series, df[sma_slow_col]).to_numpy(dtype=float)
                valid = ~np.isnan(sma_fast) & ~np.isnan(sma_slow)
                score += np.where(valid & (sma_fast > sma_slow), p.score_sma_trend, 0.0)
                score -= np.where(
                    valid & (sma_fast <= sma_slow), p.score_sma_trend, 0.0
                )

        if "ema_cross" in df.columns:
            ema_cross = cast(pd.Series, df["ema_cross"]).astype(str).to_numpy()
            score += np.where(ema_cross == "BULLISH", p.score_ema_cross, 0.0)
            score -= np.where(ema_cross == "BEARISH", p.score_ema_cross, 0.0)

        if "macd_cross" in df.columns:
            macd_cross = cast(pd.Series, df["macd_cross"]).astype(str).to_numpy()
            score += np.where(macd_cross == "BULLISH", p.score_macd_cross, 0.0)
            score -= np.where(macd_cross == "BEARISH", p.score_macd_cross, 0.0)

        if "macd_histogram" in df.columns:
            hist = cast(pd.Series, df["macd_histogram"]).to_numpy(dtype=float)
            hist_inc = (
                cast(pd.Series, df["macd_hist_increasing"]).to_numpy(dtype=bool)
                if "macd_hist_increasing" in df.columns
                else np.zeros(len(df), dtype=bool)
            )
            score += np.where((hist > 0) & hist_inc, p.score_macd_hist_strong, 0.0)
            score += np.where((hist > 0) & ~hist_inc, p.score_macd_hist_weak, 0.0)
            score -= np.where((hist < 0) & ~hist_inc, p.score_macd_hist_strong, 0.0)
            score -= np.where((hist < 0) & hist_inc, p.score_macd_hist_weak, 0.0)

        if "adx" in df.columns and "plus_di" in df.columns and "minus_di" in df.columns:
            adx = cast(pd.Series, df["adx"]).to_numpy(dtype=float)
            plus_di = cast(pd.Series, df["plus_di"]).to_numpy(dtype=float)
            minus_di = cast(pd.Series, df["minus_di"]).to_numpy(dtype=float)
            valid = ~np.isnan(adx)
            strong = valid & (adx > 25)
            weak = valid & (adx <= 25)
            score += np.where(strong & (plus_di > minus_di), p.score_adx_strong, 0.0)
            score -= np.where(strong & (plus_di <= minus_di), p.score_adx_strong, 0.0)
            score += np.where(weak & (plus_di > minus_di), p.score_adx_weak, 0.0)
            score -= np.where(weak & (plus_di <= minus_di), p.score_adx_weak, 0.0)

        if "di_cross" in df.columns:
            di_cross = cast(pd.Series, df["di_cross"]).astype(str).to_numpy()
            score += np.where(di_cross == "BULLISH", p.score_di_cross, 0.0)
            score -= np.where(di_cross == "BEARISH", p.score_di_cross, 0.0)

        # ── Volume ────────────────────────────────────────────────────
        if "volume_sma_20" in df.columns and "volume" in df.columns:
            vol = cast(pd.Series, df["volume"]).to_numpy(dtype=float)
            vol_sma = cast(pd.Series, df["volume_sma_20"]).to_numpy(dtype=float)
            min_ratio = getattr(settings, "VOLUME_CONFIRM_MULTIPLIER", 1.5)
            valid = ~np.isnan(vol_sma) & (vol_sma > 0)
            score += np.where(
                valid & (vol / np.where(vol_sma == 0, 1, vol_sma) >= min_ratio),
                p.score_volume_confirm,
                0.0,
            )

        if "volume_spike" in df.columns:
            vol_spike = cast(pd.Series, df["volume_spike"]).to_numpy(dtype=bool)
            if "_prev_close_for_scoring" in df.columns:
                price_chg = df["close"].to_numpy(dtype=float) - df[
                    "_prev_close_for_scoring"
                ].to_numpy(dtype=float)
            else:
                price_chg = np.zeros(len(df), dtype=float)
            score += np.where(vol_spike & (price_chg > 0), p.score_volume_spike, 0.0)
            score -= np.where(vol_spike & (price_chg <= 0), p.score_volume_spike, 0.0)

        if "price_volume_confirm" in df.columns:
            pvc = cast(pd.Series, df["price_volume_confirm"]).to_numpy(dtype=bool)
            score += np.where(pvc, p.score_price_volume_confirm, 0.0)

        if "volume_trend" in df.columns:
            vt = cast(pd.Series, df["volume_trend"]).astype(str).to_numpy()
            score += np.where(vt == "INCREASING", p.score_volume_trend, 0.0)
            score -= np.where(vt == "DECREASING", p.score_volume_trend, 0.0)

        if "obv_trend" in df.columns:
            obv = cast(pd.Series, df["obv_trend"]).astype(str).to_numpy()
            score += np.where(obv == "UP", p.score_obv_trend, 0.0)
            score -= np.where(obv == "DOWN", p.score_obv_trend, 0.0)

        # ── Structure ─────────────────────────────────────────────────
        if "bb_position" in df.columns:
            bb_position = cast(pd.Series, df["bb_position"]).astype(str).to_numpy()
            score += np.where(
                bb_position == "BELOW_LOWER", p.score_bollinger_extreme, 0.0
            )
            score -= np.where(
                bb_position == "ABOVE_UPPER", p.score_bollinger_extreme, 0.0
            )
        if "bb_percent" in df.columns:
            bb_pct = cast(pd.Series, df["bb_percent"]).to_numpy(dtype=float)
            score += np.where(
                ~np.isnan(bb_pct) & (bb_pct < 0.2),
                p.score_bollinger_percent,
                0.0,
            )
            score -= np.where(
                ~np.isnan(bb_pct) & (bb_pct > 0.8),
                p.score_bollinger_percent,
                0.0,
            )

        if "dist_to_support_pct" in df.columns:
            ds = cast(pd.Series, df["dist_to_support_pct"]).to_numpy(dtype=float)
            score += np.where(
                ~np.isnan(ds) & (ds < 2),
                p.score_sr_distance,
                0.0,
            )
        if "dist_to_resistance_pct" in df.columns:
            dr = cast(pd.Series, df["dist_to_resistance_pct"]).to_numpy(dtype=float)
            score -= np.where(
                ~np.isnan(dr) & (dr < 2),
                p.score_sr_distance,
                0.0,
            )

        if "rsi_divergence" in df.columns:
            rd = cast(pd.Series, df["rsi_divergence"]).astype(str).to_numpy()
            score += np.where(rd == "BULLISH", p.score_rsi_divergence, 0.0)
            score -= np.where(rd == "BEARISH", p.score_rsi_divergence, 0.0)

        if "macd_divergence" in df.columns:
            md = cast(pd.Series, df["macd_divergence"]).astype(str).to_numpy()
            score += np.where(md == "BULLISH", p.score_macd_divergence, 0.0)
            score -= np.where(md == "BEARISH", p.score_macd_divergence, 0.0)

        df["score"] = np.clip(score, -100.0, 100.0)

        if "stop_loss_atr" in df.columns:
            df["calculated_stop"] = df["stop_loss_atr"].fillna(df["close"] * 0.95)
        else:
            df["calculated_stop"] = df["close"] * 0.95

        df["risk_per_share"] = np.maximum(
            df["close"] - df["calculated_stop"], df["close"] * 0.01
        )
        df["target_price"] = np.maximum(
            df["close"] + (df["risk_per_share"] * self.target_rr), df["close"]
        )
        df["enter_signal"] = df["score"] >= self.buy_threshold
        df["exit_signal"] = df["score"] <= self.sell_threshold

        score_series = cast(pd.Series, df["score"])
        stop_series = cast(pd.Series, df["calculated_stop"])
        target_series = cast(pd.Series, df["target_price"])
        enter_series = cast(pd.Series, df["enter_signal"])
        exit_series = cast(pd.Series, df["exit_signal"])
        close_series = cast(pd.Series, df["close"])

        df["score"] = score_series.shift(1, fill_value=0.0)
        df["calculated_stop"] = stop_series.shift(
            1, fill_value=float(close_series.iloc[0]) * 0.95
        )
        df["target_price"] = target_series.shift(
            1, fill_value=float(close_series.iloc[0])
        )
        df["enter_signal"] = enter_series.shift(1, fill_value=False).astype(bool)
        df["exit_signal"] = exit_series.shift(1, fill_value=False).astype(bool)
        if len(df) >= 2:
            df.loc[df.index[:2], "score"] = 0.0
            df.loc[df.index[:2], "enter_signal"] = False
            df.loc[df.index[:2], "exit_signal"] = False
        df["stop_gap_candidate"] = (cast(pd.Series, df["calculated_stop"]) > 0) & (
            cast(pd.Series, df["open"]) <= cast(pd.Series, df["calculated_stop"])
        )
        df["target_gap_candidate"] = (cast(pd.Series, df["target_price"]) > 0) & (
            cast(pd.Series, df["open"]) >= cast(pd.Series, df["target_price"])
        )
        df["stop_hit_candidate"] = (cast(pd.Series, df["calculated_stop"]) > 0) & (
            cast(pd.Series, df["low"]) <= cast(pd.Series, df["calculated_stop"])
        )
        df["target_hit_candidate"] = (cast(pd.Series, df["target_price"]) > 0) & (
            cast(pd.Series, df["high"]) >= cast(pd.Series, df["target_price"])
        )

        return df

    def _build_vectorized_signals(self, df: pd.DataFrame) -> VectorizedSignals:
        return VectorizedSignals(
            dates=df.index.to_numpy(),
            opens=cast(pd.Series, df["open"]).to_numpy(dtype=float),
            highs=cast(pd.Series, df["high"]).to_numpy(dtype=float),
            lows=cast(pd.Series, df["low"]).to_numpy(dtype=float),
            closes=cast(pd.Series, df["close"]).to_numpy(dtype=float),
            enter_signals=cast(pd.Series, df["enter_signal"]).to_numpy(dtype=bool),
            exit_signals=cast(pd.Series, df["exit_signal"]).to_numpy(dtype=bool),
            scores=cast(pd.Series, df["score"]).to_numpy(dtype=float),
            stop_losses=cast(pd.Series, df["calculated_stop"]).to_numpy(dtype=float),
            target_prices=cast(pd.Series, df["target_price"]).to_numpy(dtype=float),
        )

    def _use_vectorized_path(self) -> bool:
        if (
            self.signal_builder is not None
            or self.meta_model is not None
            or self.mode is not BacktestMode.BASE_FIXED_SIZE
        ):
            return False
        signal_context_builder = getattr(self._build_signal_context, "__func__", None)
        return signal_context_builder is Backtester._build_signal_context

    def _find_next_entry_index(
        self,
        candidates: np.ndarray,
        start_idx: int,
        dates: np.ndarray,
        last_buy_date: datetime | None,
    ) -> int | None:
        if start_idx >= len(dates):
            return None
        next_candidates = candidates[candidates >= start_idx]
        if last_buy_date is None:
            return int(next_candidates[0]) if len(next_candidates) else None
        for idx in next_candidates:
            candidate_date = _to_datetime(dates[int(idx)])
            if (candidate_date - last_buy_date).days >= 1:
                return int(idx)
        return None

    def _find_exit_index(
        self,
        vectors: VectorizedSignals,
        entry_idx: int,
        position: dict[str, Any],
    ) -> tuple[int | None, str | None, float | None]:
        stop_loss = _to_float(position.get("stop_loss"), 0.0)
        target_price = _to_float(position.get("target_price"), 0.0)
        if entry_idx + 1 >= len(vectors.opens):
            return None, None, None

        slice_start = entry_idx + 1
        opens = vectors.opens[slice_start:]
        highs = vectors.highs[slice_start:]
        lows = vectors.lows[slice_start:]
        closes = vectors.closes[slice_start:]
        exit_signals = vectors.exit_signals[slice_start:]

        stop_gap = stop_loss > 0 and np.less_equal(opens, stop_loss)
        target_gap = target_price > 0 and np.greater_equal(opens, target_price)
        stop_hit = stop_loss > 0 and np.less_equal(lows, stop_loss)
        target_hit = target_price > 0 and np.greater_equal(highs, target_price)

        event_mask = exit_signals.copy()
        if isinstance(stop_gap, np.ndarray):
            event_mask |= stop_gap
        if isinstance(target_gap, np.ndarray):
            event_mask |= target_gap
        if isinstance(stop_hit, np.ndarray):
            event_mask |= stop_hit
        if isinstance(target_hit, np.ndarray):
            event_mask |= target_hit

        event_positions = np.flatnonzero(event_mask)
        if len(event_positions) == 0:
            return None, None, None

        rel_idx = int(event_positions[0])
        abs_idx = slice_start + rel_idx
        if bool(exit_signals[rel_idx]):
            return abs_idx, "SIGNAL_OPEN", float(opens[rel_idx])

        intrabar_exit = self._simulate_intrabar_exit(
            position,
            float(opens[rel_idx]),
            float(highs[rel_idx]),
            float(lows[rel_idx]),
            float(closes[rel_idx]),
        )
        if intrabar_exit is None:
            return None, None, None
        return abs_idx, intrabar_exit["reason"], float(intrabar_exit["reference_price"])

    def run(
        self,
        ticker: str,
        df: pd.DataFrame,
        verbose: bool = True,
        output_path: str | Path | None = None,
        universe_as_of: str | None = None,
    ) -> Optional[BacktestResult]:
        if df is None or len(df) < 50:
            logger.warning(
                "insufficient_data", row_count=len(df) if df is not None else 0
            )
            return None

        df = df.copy()
        if "rsi" not in df.columns or f"sma_{settings.SMA_SLOW}" not in df.columns:
            df = self.indicators.add_all(df)
        df = df.dropna(subset=["rsi", f"sma_{settings.SMA_SLOW}"])
        if len(df) < 2:
            return None

        if self._use_vectorized_path():
            result = self._run_vectorized(ticker, df, verbose)
        else:
            result = self._run_iterative(ticker, df, verbose)

        if result is not None:
            result.universe_as_of = universe_as_of
        if result is not None and output_path is not None:
            result.to_json(output_path)
        return result

    def run_ablation(
        self,
        ticker: str,
        df: pd.DataFrame,
        *,
        verbose: bool = False,
    ) -> BacktestAblationResult:
        runs: dict[str, BacktestResult] = {}
        for mode in (
            BacktestMode.BASE_FIXED_SIZE,
            BacktestMode.META_FILTER_FIXED_SIZE,
            BacktestMode.META_FILTER_FRACTIONAL_KELLY,
        ):
            backtester = self._clone_for_mode(mode)
            result = backtester.run(ticker, df, verbose=verbose)
            if result is not None:
                runs[mode.value] = result

        base = runs.get(BacktestMode.BASE_FIXED_SIZE.value)
        comparisons: dict[str, dict[str, AblationComparison]] = {}
        if base is not None:
            for mode_name, result in runs.items():
                if mode_name == BacktestMode.BASE_FIXED_SIZE.value:
                    continue
                comparisons[mode_name] = {
                    metric: AblationComparison(
                        base_metric=float(getattr(base, metric)),
                        candidate_metric=float(getattr(result, metric)),
                        delta=float(getattr(result, metric))
                        - float(getattr(base, metric)),
                    )
                    for metric in (
                        "cagr",
                        "sharpe_ratio",
                        "sortino_ratio",
                        "max_drawdown_pct",
                        "calmar_ratio",
                        "win_rate",
                        "profit_factor",
                        "turnover_ratio",
                        "exposure_pct",
                        "tail_loss_pct",
                    )
                }
        return BacktestAblationResult(ticker=ticker, runs=runs, comparisons=comparisons)

    def _clone_for_mode(self, mode: BacktestMode) -> "Backtester":
        clone = Backtester(
            initial_capital=self.initial_capital,
            commission_buy_pct=self.commission_buy_pct
            if self.cost_model is None
            else None,
            commission_sell_pct=self.commission_sell_pct
            if self.cost_model is None
            else None,
            buy_threshold=self.buy_threshold,
            sell_threshold=self.sell_threshold,
            slippage_pct=self.slippage_pct if self.cost_model is None else None,
            target_rr=self.target_rr,
            indicators=self.indicators,
            cost_model=self.cost_model,
            meta_model=(
                self.meta_model if mode is not BacktestMode.BASE_FIXED_SIZE else None
            ),
            mode=mode,
            min_probability=self.min_probability,
            fractional_kelly=self.fractional_kelly,
            max_position_cap_pct=self.max_position_cap_pct,
        )
        clone.signal_builder = self.signal_builder
        return clone

    def _run_vectorized(
        self,
        ticker: str,
        df: pd.DataFrame,
        verbose: bool,
    ) -> Optional[BacktestResult]:
        df = self._precalculate_signals(df)
        vectors = self._build_vectorized_signals(df)
        entry_candidates = np.flatnonzero(vectors.enter_signals)

        capital = self.initial_capital
        trades: list[BacktestTrade] = []
        capital_history = np.empty(len(df) + 1, dtype=float)
        capital_history[0] = capital
        last_buy_date: Optional[datetime] = None
        cursor = 0

        while cursor < len(df):
            entry_idx = self._find_next_entry_index(
                entry_candidates, cursor, vectors.dates, last_buy_date
            )
            if entry_idx is None:
                capital_history[cursor + 1 :] = capital
                break

            if entry_idx > cursor:
                capital_history[cursor + 1 : entry_idx + 1] = capital

            date = _to_datetime(vectors.dates[entry_idx])
            open_price = float(vectors.opens[entry_idx])
            close_price = float(vectors.closes[entry_idx])
            signal = {
                "enter": True,
                "exit": bool(vectors.exit_signals[entry_idx]),
                "score": float(vectors.scores[entry_idx]),
                "stop_loss": float(vectors.stop_losses[entry_idx]),
                "target_price": float(vectors.target_prices[entry_idx]),
            }
            row = df.iloc[entry_idx]
            estimated_shares = self._estimate_entry_shares(
                capital,
                open_price,
                _to_float(signal.get("position_fraction"), 1.0),
            )
            entry_fill_price = self._calculate_fill_price(
                open_price, row, is_buy=True, shares=estimated_shares
            )
            position = self._open_position(
                signal, entry_fill_price, open_price, date, capital
            )

            if position is None:
                capital_history[entry_idx + 1] = capital
                cursor = entry_idx + 1
                continue

            capital -= position["cost"]
            last_buy_date = date
            if verbose:
                logger.info(
                    f"  🟢 AL: {date.strftime('%d.%m')} | "
                    f"₺{position['entry_price']:.2f} x {position['shares']} lot | "
                    f"Skor: {position['score']:+.0f}"
                )

            same_bar_exit = self._simulate_intrabar_exit(
                position,
                open_price,
                float(vectors.highs[entry_idx]),
                float(vectors.lows[entry_idx]),
                close_price,
            )
            if same_bar_exit is not None:
                ref_price = float(same_bar_exit["reference_price"])
                capital = self._close_position(
                    capital=capital,
                    position=position,
                    trades=trades,
                    ticker=ticker,
                    exit_date=date,
                    fill_price=self._calculate_fill_price(
                        ref_price, row, is_buy=False, shares=int(position["shares"])
                    ),
                    reference_price=ref_price,
                    reason=same_bar_exit["reason"],
                    verbose=verbose,
                )
                capital_history[entry_idx + 1] = capital
                cursor = entry_idx + 1
                continue

            exit_idx, exit_reason, reference_price = self._find_exit_index(
                vectors, entry_idx, position
            )
            held_equity = (
                capital + float(position["shares"]) * vectors.closes[entry_idx:]
            )

            if exit_idx is None or exit_reason is None or reference_price is None:
                capital_history[entry_idx + 1 :] = held_equity
                last_idx = len(df) - 1
                last_row = df.iloc[last_idx]
                last_date = _to_datetime(vectors.dates[last_idx])
                last_close = float(vectors.closes[last_idx])
                capital = self._close_position(
                    capital=capital,
                    position=position,
                    trades=trades,
                    ticker=ticker,
                    exit_date=last_date,
                    fill_price=self._calculate_fill_price(
                        last_close,
                        last_row,
                        is_buy=False,
                        shares=int(position["shares"]),
                    ),
                    reference_price=last_close,
                    reason="FINAL_CLOSE",
                    verbose=False,
                )
                capital_history[-1] = capital
                cursor = len(df)
                break

            capital_history[entry_idx + 1 : exit_idx + 1] = held_equity[
                : exit_idx - entry_idx
            ]
            exit_row = df.iloc[exit_idx]
            exit_date = _to_datetime(vectors.dates[exit_idx])
            capital = self._close_position(
                capital=capital,
                position=position,
                trades=trades,
                ticker=ticker,
                exit_date=exit_date,
                fill_price=self._calculate_fill_price(
                    reference_price,
                    exit_row,
                    is_buy=False,
                    shares=int(position["shares"]),
                ),
                reference_price=reference_price,
                reason=exit_reason,
                verbose=verbose,
            )
            capital_history[exit_idx + 1] = capital
            cursor = exit_idx + 1

        return self._build_result(ticker, df, capital, trades, capital_history.tolist())

    def _run_iterative(
        self,
        ticker: str,
        df: pd.DataFrame,
        verbose: bool,
    ) -> Optional[BacktestResult]:
        capital = self.initial_capital
        position: Optional[dict[str, Any]] = None
        trades: list[BacktestTrade] = []
        capital_history: list[float] = [capital]
        last_buy_date: Optional[datetime] = None

        for i in range(1, len(df)):
            history = df.iloc[:i]
            bar = df.iloc[i]
            date = _to_datetime(df.index[i])
            open_price = _to_float(bar.get("open"), _to_float(bar.get("close")))
            high_price = _to_float(bar.get("high"), open_price)
            low_price = _to_float(bar.get("low"), open_price)
            close_price = _to_float(bar.get("close"), open_price)

            signal = self._build_signal_context(ticker, history)

            if position is not None and self._should_exit_on_open(signal):
                exit_fill_price = self._calculate_fill_price(
                    open_price,
                    bar,
                    is_buy=False,
                    shares=int(position["shares"]),
                )
                capital = self._close_position(
                    capital=capital,
                    position=position,
                    trades=trades,
                    ticker=ticker,
                    exit_date=date,
                    fill_price=exit_fill_price,
                    reference_price=open_price,
                    reason="SIGNAL_OPEN",
                    verbose=verbose,
                )
                position = None

            if position is None and self._should_enter_on_open(signal):
                if last_buy_date is None or (date - last_buy_date).days >= 1:
                    estimated_shares = self._estimate_entry_shares(
                        capital,
                        open_price,
                        _to_float(signal.get("position_fraction"), 1.0),
                    )
                    entry_fill_price = self._calculate_fill_price(
                        open_price,
                        bar,
                        is_buy=True,
                        shares=estimated_shares,
                    )
                    position = self._open_position(
                        signal, entry_fill_price, open_price, date, capital
                    )
                    if position is not None:
                        capital -= position["cost"]
                        last_buy_date = date
                        if verbose:
                            logger.info(
                                f"  🟢 AL: {date.strftime('%d.%m')} | "
                                f"₺{position['entry_price']:.2f} x {position['shares']} lot | "
                                f"Skor: {position['score']:+.0f}"
                            )

            if position is not None:
                intrabar_exit = self._simulate_intrabar_exit(
                    position, open_price, high_price, low_price, close_price
                )
                if intrabar_exit is not None:
                    ref_price = intrabar_exit["reference_price"]
                    exit_fill_price = self._calculate_fill_price(
                        ref_price,
                        bar,
                        is_buy=False,
                        shares=int(position["shares"]),
                    )
                    capital = self._close_position(
                        capital=capital,
                        position=position,
                        trades=trades,
                        ticker=ticker,
                        exit_date=date,
                        fill_price=exit_fill_price,
                        reference_price=ref_price,
                        reason=intrabar_exit["reason"],
                        verbose=verbose,
                    )
                    position = None

            equity = (
                capital
                if position is None
                else capital + position["shares"] * close_price
            )
            capital_history.append(equity)

        if position is not None:
            last_date = _to_datetime(df.index[-1])
            last_bar = df.iloc[-1]
            last_close = _to_float(last_bar.get("close"))
            capital = self._close_position(
                capital=capital,
                position=position,
                trades=trades,
                ticker=ticker,
                exit_date=last_date,
                fill_price=self._calculate_fill_price(
                    last_close,
                    last_bar,
                    is_buy=False,
                    shares=int(position["shares"]),
                ),
                reference_price=last_close,
                reason="FINAL_CLOSE",
                verbose=False,
            )
            capital_history[-1] = capital

        return self._build_result(ticker, df, capital, trades, capital_history)

    def _build_signal_context(
        self, ticker: str, history: pd.DataFrame
    ) -> dict[str, float | bool]:
        if self.signal_builder is not None:
            return self.signal_builder(ticker, history)
        score = self._calculate_score(history)
        last_close = _to_float(history.iloc[-1].get("close"))
        stop_loss = _to_float(history.iloc[-1].get("stop_loss_atr"), last_close * 0.95)
        risk_per_share = max(last_close - stop_loss, last_close * 0.01)
        target_price = max(last_close + risk_per_share * self.target_rr, last_close)
        signal: dict[str, float | bool] = {
            "enter": score >= self.buy_threshold,
            "exit": score <= self.sell_threshold,
            "score": score,
            "stop_loss": stop_loss,
            "target_price": target_price,
        }
        signal.update(self._meta_signal_fields(history, score, stop_loss, target_price))
        return signal

    def _meta_signal_fields(
        self,
        history: pd.DataFrame,
        score: float,
        stop_loss: float,
        target_price: float,
    ) -> dict[str, float | bool]:
        if self.meta_model is None or history.empty:
            return {}
        last = history.iloc[-1]
        last_close = _to_float(last.get("close"))
        if last_close <= 0:
            return {}
        risk_per_share = max(last_close - stop_loss, last_close * 0.01)
        reward_per_share = max(target_price - last_close, 0.0)
        reward_to_risk = (
            reward_per_share / risk_per_share if risk_per_share > 0 else 0.0
        )
        probability = float(
            self.meta_model.predict_probability(
                build_feature_payload(
                    last,
                    score=score,
                    stop_loss=stop_loss,
                    target_price=target_price,
                )
            )
        )
        fields: dict[str, float | bool] = {"signal_probability": probability}
        if self.mode is BacktestMode.META_FILTER_FIXED_SIZE:
            fields["enter"] = bool(
                score >= self.buy_threshold and probability >= self.min_probability
            )
            fields["position_fraction"] = 1.0
        elif self.mode is BacktestMode.META_FILTER_FRACTIONAL_KELLY:
            full_kelly = calculate_kelly_fraction(probability, reward_to_risk)
            kelly_fraction = min(
                self.max_position_cap_pct / 100.0,
                max(0.0, full_kelly * self.fractional_kelly),
            )
            fields["enter"] = bool(
                score >= self.buy_threshold
                and probability >= self.min_probability
                and kelly_fraction > 0
            )
            fields["position_fraction"] = kelly_fraction
            fields["kelly_fraction"] = kelly_fraction
        return fields

    def _should_enter_on_open(self, signal: dict[str, float | bool]) -> bool:
        return bool(signal.get("enter"))

    def _should_exit_on_open(self, signal: dict[str, float | bool]) -> bool:
        return bool(signal.get("exit"))

    def _fee_components(self, notional: float) -> dict[str, float]:
        if self.cost_model is None:
            return {
                "commission": 0.0,
                "bsmv": 0.0,
                "exchange_fee": 0.0,
                "total": 0.0,
            }

        commission = notional * (self.cost_model.commission_bps / 10_000)
        bsmv = notional * (self.cost_model.bsmv_bps / 10_000)
        exchange_fee = notional * (self.cost_model.exchange_fee_bps / 10_000)
        return {
            "commission": commission,
            "bsmv": bsmv,
            "exchange_fee": exchange_fee,
            "total": commission + bsmv + exchange_fee,
        }

    def _extract_row_value(self, row: Any, key: str, default: float = 0.0) -> float:
        if hasattr(row, key):
            return _to_float(getattr(row, key), default)
        if isinstance(row, pd.Series):
            return _to_float(row.get(key), default)
        return default

    def _calculate_slippage_bps(self, price: float, row: Any, shares: int) -> float:
        if self.cost_model is None:
            return 0.0

        model = self.cost_model
        if model.slippage_model == "fixed":
            return model.fixed_slippage_bps

        if model.slippage_model == "volume_aware":
            avg_daily_volume = self._extract_row_value(row, "volume_sma_20", 0.0)
            if avg_daily_volume <= 0:
                avg_daily_volume = self._extract_row_value(row, "volume", 0.0)
            if avg_daily_volume <= 0:
                return model.fixed_slippage_bps
            volume_ratio = shares / avg_daily_volume
            return min(
                volume_ratio * model.volume_slippage_bps_per_volume_ratio,
                model.max_slippage_bps,
            )

        if model.slippage_model == "atr_aware":
            atr_value = self._extract_row_value(row, "atr", 0.0)
            if atr_value <= 0 or price <= 0:
                return model.fixed_slippage_bps
            atr_ratio = atr_value / price
            return min(
                atr_ratio * model.atr_slippage_ratio * 10_000, model.max_slippage_bps
            )

        return model.fixed_slippage_bps

    def _estimate_entry_shares(
        self, capital: float, price: float, position_fraction: float = 1.0
    ) -> int:
        if price <= 0:
            return 0
        deployable_capital = capital * max(0.0, min(1.0, position_fraction))
        return max(int(deployable_capital / price), 1) if deployable_capital > 0 else 0

    def _calculate_fill_price(
        self, price: float, row: Any, is_buy: bool, shares: int
    ) -> float:
        if self.cost_model is not None:
            slippage_pct = self._calculate_slippage_bps(price, row, shares) / 10_000
            return price * (1 + slippage_pct if is_buy else 1 - slippage_pct)
        return self._calculate_dynamic_slippage(price, row, is_buy=is_buy)

    def _calculate_dynamic_slippage(
        self, price: float, row: Any, is_buy: bool
    ) -> float:
        """Calculate volatility-aware slippage using ATR when available."""
        base_slippage = float(getattr(settings, "SLIPPAGE_PCT", 0.001))
        penalty_ratio = float(getattr(settings, "SLIPPAGE_PENALTY_RATIO", 0.15))
        max_cap = float(getattr(settings, "SLIPPAGE_MAX_CAP", 0.02))

        atr_val = None
        if hasattr(row, "atr"):
            atr_val = row.atr
        elif isinstance(row, pd.Series) and "atr" in row:
            atr_val = row["atr"]

        atr_float = _to_float(atr_val, 0.0)
        if atr_float > 0 and price > 0:
            volatility_ratio = atr_float / price
            penalty_pct = volatility_ratio * penalty_ratio
            dynamic_slippage_pct = base_slippage + penalty_pct
        else:
            dynamic_slippage_pct = base_slippage

        dynamic_slippage_pct = float(min(dynamic_slippage_pct, max_cap))
        if is_buy:
            return price * (1 + dynamic_slippage_pct)
        return price * (1 - dynamic_slippage_pct)

    def _open_position(
        self,
        signal: dict[str, float | bool],
        fill_price: float,
        reference_price: float,
        entry_date: datetime,
        capital: float,
    ) -> Optional[dict[str, Any]]:
        entry_price = fill_price
        position_fraction = max(
            0.0, min(1.0, _to_float(signal.get("position_fraction"), 1.0))
        )
        capital_to_deploy = capital * position_fraction
        if self.cost_model is None:
            unit_cost = entry_price * (1 + self.commission_buy_pct)
            shares = int(capital_to_deploy / unit_cost) if unit_cost > 0 else 0
            entry_fee_tl = shares * entry_price * self.commission_buy_pct
            entry_bsmv_tl = 0.0
            entry_exchange_fee_tl = 0.0
        else:
            fee_pct = (
                self.cost_model.commission_bps
                + self.cost_model.bsmv_bps
                + self.cost_model.exchange_fee_bps
            ) / 10_000
            unit_cost = entry_price * (1 + fee_pct)
            shares = int(capital_to_deploy / unit_cost) if unit_cost > 0 else 0
            fee_components = self._fee_components(shares * entry_price)
            entry_fee_tl = fee_components["commission"]
            entry_bsmv_tl = fee_components["bsmv"]
            entry_exchange_fee_tl = fee_components["exchange_fee"]
        if shares <= 0:
            return None

        if self.cost_model is None:
            cost = shares * unit_cost
        else:
            cost = (
                shares * entry_price
                + entry_fee_tl
                + entry_bsmv_tl
                + entry_exchange_fee_tl
            )
        entry_slippage_tl = shares * max(entry_price - reference_price, 0.0)
        return {
            "entry_date": entry_date,
            "entry_price": entry_price,
            "reference_entry_price": reference_price,
            "shares": shares,
            "cost": cost,
            "stop_loss": _to_float(signal.get("stop_loss"), entry_price * 0.95),
            "target_price": _to_float(signal.get("target_price"), 0.0),
            "score": _to_float(signal.get("score"), 0.0),
            "signal_probability": signal.get("signal_probability"),
            "position_fraction": position_fraction,
            "entry_fee_tl": entry_fee_tl,
            "entry_bsmv_tl": entry_bsmv_tl,
            "entry_exchange_fee_tl": entry_exchange_fee_tl,
            "entry_slippage_tl": entry_slippage_tl,
            "entry_notional_tl": shares * entry_price,
        }

    def _simulate_intrabar_exit(
        self,
        position: dict[str, Any],
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
    ) -> Optional[IntrabarExit]:
        stop_loss = _to_float(position.get("stop_loss"), 0.0)
        target_price = _to_float(position.get("target_price"), 0.0)
        if stop_loss <= 0 and target_price <= 0:
            return None

        if stop_loss > 0 and open_price <= stop_loss:
            return {
                "reason": "STOP_GAP",
                "reference_price": open_price,
            }

        if target_price > 0 and open_price >= target_price:
            return {
                "reason": "TARGET_GAP",
                "reference_price": open_price,
            }

        stop_hit = stop_loss > 0 and low_price <= stop_loss
        target_hit = target_price > 0 and high_price >= target_price

        if not stop_hit and not target_hit:
            return None

        if stop_hit and target_hit:
            # OHLC bars do not reveal whether stop or target traded first.
            # Use the conservative fill for long-only simulations instead of
            # inferring an impossible intrabar path from open/close direction.
            first_reason = "STOP_LOSS"
            first_price = stop_loss
        elif stop_hit:
            first_reason = "STOP_LOSS"
            first_price = stop_loss
        else:
            first_reason = "TAKE_PROFIT"
            first_price = target_price

        return {
            "reason": first_reason,
            "reference_price": first_price,
        }

    def _close_position(
        self,
        capital: float,
        position: dict[str, Any],
        trades: list[BacktestTrade],
        ticker: str,
        exit_date: datetime,
        fill_price: float,
        reference_price: float,
        reason: str,
        verbose: bool,
    ) -> float:
        notional = position["shares"] * fill_price
        if self.cost_model is None:
            exit_fee_tl = notional * self.commission_sell_pct
            exit_bsmv_tl = 0.0
            exit_exchange_fee_tl = 0.0
        else:
            fee_components = self._fee_components(notional)
            exit_fee_tl = fee_components["commission"]
            exit_bsmv_tl = fee_components["bsmv"]
            exit_exchange_fee_tl = fee_components["exchange_fee"]

        revenue = notional - exit_fee_tl - exit_bsmv_tl - exit_exchange_fee_tl
        profit_tl = revenue - position["cost"]
        profit_pct = (profit_tl / position["cost"]) * 100 if position["cost"] else 0.0
        holding_days = max((exit_date - position["entry_date"]).days, 0)
        gross_profit_tl = position["shares"] * (
            reference_price - position["reference_entry_price"]
        )
        exit_slippage_tl = position["shares"] * max(reference_price - fill_price, 0.0)
        total_commission_tl = position["entry_fee_tl"] + exit_fee_tl
        total_bsmv_tl = position["entry_bsmv_tl"] + exit_bsmv_tl
        total_exchange_fee_tl = position["entry_exchange_fee_tl"] + exit_exchange_fee_tl
        total_slippage_tl = position["entry_slippage_tl"] + exit_slippage_tl
        total_cost_tl = (
            total_commission_tl
            + total_bsmv_tl
            + total_exchange_fee_tl
            + total_slippage_tl
        )

        trades.append(
            BacktestTrade(
                entry_date=position["entry_date"],
                exit_date=exit_date,
                ticker=ticker,
                entry_price=round(position["entry_price"], 4),
                exit_price=round(fill_price, 4),
                signal_score=position["score"],
                profit_pct=round(profit_pct, 2),
                profit_tl=round(profit_tl, 2),
                holding_days=holding_days,
                exit_reason=reason,
                gross_profit_tl=round(gross_profit_tl, 2),
                entry_notional_tl=round(
                    float(position.get("entry_notional_tl", 0.0)), 2
                ),
                total_cost_tl=round(total_cost_tl, 2),
                commission_tl=round(total_commission_tl, 2),
                bsmv_tl=round(total_bsmv_tl, 2),
                exchange_fee_tl=round(total_exchange_fee_tl, 2),
                slippage_tl=round(total_slippage_tl, 2),
                signal_probability=(
                    round(_to_float(cast(Any, position.get("signal_probability"))), 4)
                    if position.get("signal_probability") is not None
                    else None
                ),
                position_fraction=round(
                    float(position.get("position_fraction", 1.0)), 4
                ),
            )
        )

        if verbose:
            emoji = "✅" if profit_tl > 0 else "❌"
            logger.info(
                f"  🔴 SAT ({reason}): {exit_date.strftime('%d.%m')} | "
                f"₺{reference_price:.2f} -> ₺{fill_price:.2f} | "
                f"{emoji} {profit_pct:+.1f}% (₺{profit_tl:+.0f}) | {holding_days} gün"
            )

        return float(capital + revenue)

    def _build_result(
        self,
        ticker: str,
        df: pd.DataFrame,
        capital: float,
        trades: list[BacktestTrade],
        capital_history: list[float],
    ) -> BacktestResult:
        avg_holding = 0.0
        idle_ratio = 0.0
        if trades:
            holding_days = [t.holding_days for t in trades]
            avg_holding = round(float(np.mean(holding_days)), 1)
            total_days = (_to_datetime(df.index[-1]) - _to_datetime(df.index[0])).days
            if total_days > 0:
                idle_ratio = round(
                    (total_days - sum(holding_days)) / total_days * 100, 1
                )

        self.avg_holding_days = avg_holding
        logger.info(
            "avg_holding_stats", avg_holding_days=avg_holding, idle_pct=idle_ratio
        )

        summary = _summarize_trades_and_equity(
            ticker=ticker,
            start_date=_to_datetime(df.index[0]),
            end_date=_to_datetime(df.index[-1]),
            initial_capital=self.initial_capital,
            final_capital=capital,
            trades=trades,
            equity_history=capital_history,
        )

        return BacktestResult(
            ticker=summary["ticker"],
            period=summary["period"],
            initial_capital=summary["initial_capital"],
            final_capital=summary["final_capital"],
            total_return_pct=summary["total_return_pct"],
            total_trades=summary["total_trades"],
            winning_trades=summary["winning_trades"],
            losing_trades=summary["losing_trades"],
            win_rate=summary["win_rate"],
            avg_profit_pct=summary["avg_profit_pct"],
            avg_loss_pct=summary["avg_loss_pct"],
            max_drawdown_pct=summary["max_drawdown_pct"],
            sharpe_ratio=summary["sharpe_ratio"],
            sortino_ratio=summary["sortino_ratio"],
            cagr=summary["cagr"],
            calmar_ratio=summary["calmar_ratio"],
            profit_factor=summary["profit_factor"],
            avg_trade_pct=summary["avg_trade_pct"],
            exposure_pct=summary["exposure_pct"],
            turnover_ratio=summary["turnover_ratio"],
            tail_loss_pct=summary["tail_loss_pct"],
            longest_loss_streak=summary["longest_loss_streak"],
            probability_diagnostics=summary["probability_diagnostics"],
            mode=self.mode.value,
            cost_breakdown=cast(CostBreakdown, summary["cost_breakdown"]),
            trades=trades,
        )

    def _calculate_score(self, df: pd.DataFrame) -> float:
        from bist_bot.strategy.params import StrategyParams
        from bist_bot.strategy.scoring import (
            score_momentum,
            score_trend,
            score_volume,
            score_structure,
        )

        if len(df) < 2:
            return 0.0

        last = df.iloc[-1]
        prev = df.iloc[-2]
        p = StrategyParams()

        s1, _ = score_momentum(p, last, prev)
        s2, _ = score_trend(p, last, prev)
        s3, _ = score_volume(p, last)
        s4, _ = score_structure(p, last)

        return max(-100.0, min(100.0, s1 + s2 + s3 + s4))


class StrategyBacktester:
    def __init__(
        self,
        initial_capital: Optional[float] = None,
        engine: Optional[StrategyEngineProtocol] = None,
        backtester: Optional[Backtester] = None,
    ) -> None:
        self.engine = engine or strategy_module.StrategyEngine()
        self.backtester = backtester or Backtester(
            initial_capital=initial_capital,
            indicators=TechnicalIndicators(),
        )
        self._enriched_cache: Optional[pd.DataFrame] = None

    @staticmethod
    def _empty_signal_context() -> dict[str, float | bool]:
        return {
            "enter": False,
            "exit": False,
            "score": 0.0,
            "stop_loss": 0.0,
            "target_price": 0.0,
        }

    def run(
        self, ticker: str, df: pd.DataFrame, verbose: bool = False
    ) -> Optional[BacktestResult]:
        self._enriched_cache = TechnicalIndicators().add_all(df.copy())

        def signal_builder(
            ticker: str, history: pd.DataFrame
        ) -> dict[str, float | bool]:
            idx = len(history) - 1
            if (
                self._enriched_cache is None
                or idx < 0
                or idx >= len(self._enriched_cache)
            ):
                return self._empty_signal_context()

            enriched_slice = self._enriched_cache.iloc[: idx + 1]
            signal = self.engine.analyze(
                ticker, enriched_slice, enforce_sector_limit=False
            )
            if signal is None:
                return self._empty_signal_context()
            return {
                "enter": signal.signal_type in {SignalType.STRONG_BUY, SignalType.BUY},
                "exit": signal.signal_type in {SignalType.SELL, SignalType.STRONG_SELL},
                "score": signal.score,
                "stop_loss": signal.stop_loss,
                "target_price": signal.target_price,
            }

        self.backtester.signal_builder = signal_builder
        try:
            return self.backtester.run(ticker, self._enriched_cache, verbose=verbose)
        finally:
            self.backtester.signal_builder = None
            self._enriched_cache = None


class WalkForwardValidator:
    def __init__(
        self,
        train_window: int = 12,
        test_window: int = 3,
        step: int = 3,
        mode: str = WindowMode.ROLLING.value,
        optimizer_iterations: int = 20,
        param_grid: Optional[dict[str, list[Any]]] = None,
        optimizer_factory: Any | None = None,
        backtester_factory: Any | None = None,
    ) -> None:
        self.train_window = train_window
        self.test_window = test_window
        self.step = step
        self.mode = WindowMode(mode)
        self.optimizer_iterations = optimizer_iterations
        self.param_grid = param_grid or {
            "buy_threshold": [12.0, 15.0, 20.0],
            "sell_threshold": [-12.0, -20.0, -28.0],
            "score_macd_cross": [8.0, 12.0, 15.0],
            "score_sma_golden_cross": [10.0, 12.0, 15.0],
        }
        self.optimizer_factory = optimizer_factory
        self.backtester_factory = backtester_factory

    def _build_windows(
        self, df: pd.DataFrame
    ) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        windows: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        if df.empty:
            return windows

        index = pd.DatetimeIndex(df.index)
        start_date = _to_datetime(index.min())
        end_date = _to_datetime(index.max())
        current_train_start = pd.Timestamp(start_date)
        current_train_months = self.train_window

        while True:
            train_end = current_train_start + pd.DateOffset(months=current_train_months)
            test_end = train_end + pd.DateOffset(months=self.test_window)
            if test_end > end_date:
                break

            train_df = df.loc[
                (df.index >= current_train_start) & (df.index < train_end)
            ]
            test_df = df.loc[(df.index >= train_end) & (df.index < test_end)]
            if not train_df.empty and not test_df.empty:
                windows.append((train_df, test_df))

            if self.mode is WindowMode.ROLLING:
                current_train_start = current_train_start + pd.DateOffset(
                    months=self.step
                )
            else:
                current_train_start = pd.Timestamp(start_date)
                current_train_months += self.step

        return windows

    def _optimizer(
        self, ticker: str, train_df: pd.DataFrame, initial_capital: float
    ) -> Any:
        if self.optimizer_factory is not None:
            return self.optimizer_factory(ticker, train_df, initial_capital)

        from bist_bot.optimizer import StrategyOptimizer

        return StrategyOptimizer(
            ticker=ticker, df=train_df, initial_capital=initial_capital
        )

    def _backtester(self, initial_capital: float, params: Any) -> StrategyBacktester:
        if self.backtester_factory is not None:
            return cast(
                StrategyBacktester, self.backtester_factory(initial_capital, params)
            )

        engine = strategy_module.StrategyEngine(params=params)
        return StrategyBacktester(initial_capital=initial_capital, engine=engine)

    def run(
        self,
        ticker: str,
        df: pd.DataFrame,
        initial_capital: Optional[float] = None,
        output_path: str | Path | None = None,
        universe_as_of: str | None = None,
    ) -> Optional[WalkForwardResult]:
        if df is None or df.empty:
            return None

        initial = (
            float(initial_capital)
            if initial_capital is not None
            else float(getattr(settings, "INITIAL_CAPITAL", 8500.0))
        )
        df_sorted = df.sort_index()
        windows = self._build_windows(df_sorted)
        if not windows:
            return None

        compounded_capital = initial
        equity_history = [initial]
        combined_trades: list[BacktestTrade] = []
        window_results: list[WalkForwardWindowResult] = []

        for idx, (train_df, test_df) in enumerate(windows, start=1):
            optimizer = self._optimizer(ticker, train_df, initial)
            best_params, _ = optimizer.random_search(
                self.param_grid, n_iter=self.optimizer_iterations
            )
            if best_params is None:
                continue

            backtester = self._backtester(initial, best_params)
            test_result = backtester.run(ticker, test_df, verbose=False)
            if test_result is None:
                continue

            compounded_capital *= 1 + (test_result.total_return_pct / 100)
            equity_history.append(compounded_capital)
            combined_trades.extend(test_result.trades)

            params_dict = getattr(best_params, "__dict__", {})
            window_results.append(
                WalkForwardWindowResult(
                    window_index=idx,
                    train_period=f"{_to_datetime(train_df.index[0]).strftime('%Y-%m-%d')} -> {_to_datetime(train_df.index[-1]).strftime('%Y-%m-%d')}",
                    test_period=f"{_to_datetime(test_df.index[0]).strftime('%Y-%m-%d')} -> {_to_datetime(test_df.index[-1]).strftime('%Y-%m-%d')}",
                    train_rows=len(train_df),
                    test_rows=len(test_df),
                    params={
                        key: value
                        for key, value in params_dict.items()
                        if key in self.param_grid
                    },
                    metrics=test_result.to_dict(),
                )
            )

        if not window_results:
            return None

        combined_summary = _summarize_trades_and_equity(
            ticker=ticker,
            start_date=_to_datetime(df_sorted.index[0]),
            end_date=_to_datetime(df_sorted.index[-1]),
            initial_capital=initial,
            final_capital=compounded_capital,
            trades=combined_trades,
            equity_history=equity_history,
        )
        combined_metrics = {
            "sharpe": combined_summary["sharpe_ratio"],
            "sortino": combined_summary["sortino_ratio"],
            "max_drawdown": combined_summary["max_drawdown_pct"],
            "cagr": combined_summary["cagr"],
            "win_rate": combined_summary["win_rate"],
            "profit_factor": combined_summary["profit_factor"],
            "avg_trade": combined_summary["avg_trade_pct"],
            "total_return_pct": combined_summary["total_return_pct"],
            "final_capital": combined_summary["final_capital"],
            "total_trades": combined_summary["total_trades"],
        }

        result = WalkForwardResult(
            ticker=ticker,
            initial_capital=initial,
            final_capital=round(compounded_capital, 2),
            train_window_months=self.train_window,
            test_window_months=self.test_window,
            step_months=self.step,
            mode=self.mode.value,
            universe_as_of=universe_as_of,
            windows=window_results,
            combined_metrics=combined_metrics,
        )

        if output_path is not None:
            result.to_json(output_path)
        return result


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


def calculate_metrics(trades, benchmark_return: Optional[float] = None) -> dict:
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


def generate_report(
    result: BacktestResult, benchmark_return: Optional[float] = None
) -> str:
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


def compare_benchmark(ticker: str, df: pd.DataFrame) -> float:
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
