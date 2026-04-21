import json
import logging
import importlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, TypedDict, cast

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import settings
import strategy as strategy_module
from contracts import StrategyEngineProtocol
from indicators import TechnicalIndicators
from signal_models import SignalType

logger = logging.getLogger(__name__)


class IntrabarExit(TypedDict):
    reason: str
    reference_price: float


class SignalBuilder(Protocol):
    def __call__(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
        ...


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
        }


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
    ):
        self.initial_capital = float(
            initial_capital if initial_capital is not None else getattr(settings, "INITIAL_CAPITAL", 8500.0)
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
            slippage_pct if slippage_pct is not None else getattr(settings, "BACKTEST_SLIPPAGE_PCT", 0.0005)
        )
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

    def _precalculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Precompute default backtest signals in a vectorized form."""
        df = df.copy()
        df["score"] = 0.0

        if "rsi" in df.columns:
            df.loc[df["rsi"] < settings.RSI_OVERSOLD, "score"] += 20
            df.loc[df["rsi"] > settings.RSI_OVERBOUGHT, "score"] -= 20

        if "sma_cross" in df.columns:
            df.loc[df["sma_cross"] == "GOLDEN_CROSS", "score"] += 20
            df.loc[df["sma_cross"] == "DEATH_CROSS", "score"] -= 20

        sma_fast_col = f"sma_{settings.SMA_FAST}"
        sma_slow_col = f"sma_{settings.SMA_SLOW}"
        if sma_fast_col in df.columns and sma_slow_col in df.columns:
            df.loc[df[sma_fast_col] > df[sma_slow_col], "score"] += 5
            df.loc[df[sma_fast_col] <= df[sma_slow_col], "score"] -= 5

        if "macd_cross" in df.columns:
            df.loc[df["macd_cross"] == "BULLISH", "score"] += 15
            df.loc[df["macd_cross"] == "BEARISH", "score"] -= 15

        if "bb_position" in df.columns:
            df.loc[df["bb_position"] == "BELOW_LOWER", "score"] += 10
            df.loc[df["bb_position"] == "ABOVE_UPPER", "score"] -= 10

        df["score"] = df["score"].clip(lower=-100.0, upper=100.0)

        if "stop_loss_atr" in df.columns:
            df["calculated_stop"] = df["stop_loss_atr"].fillna(df["close"] * 0.95)
        else:
            df["calculated_stop"] = df["close"] * 0.95

        df["risk_per_share"] = np.maximum(df["close"] - df["calculated_stop"], df["close"] * 0.01)
        df["target_price"] = np.maximum(df["close"] + (df["risk_per_share"] * self.target_rr), df["close"])
        df["enter_signal"] = df["score"] >= self.buy_threshold
        df["exit_signal"] = df["score"] <= self.sell_threshold

        score_series = cast(pd.Series, df["score"])
        stop_series = cast(pd.Series, df["calculated_stop"])
        target_series = cast(pd.Series, df["target_price"])
        enter_series = cast(pd.Series, df["enter_signal"])
        exit_series = cast(pd.Series, df["exit_signal"])
        close_series = cast(pd.Series, df["close"])

        df["score"] = score_series.shift(1).fillna(0.0)
        df["calculated_stop"] = stop_series.shift(1).fillna(close_series * 0.95)
        df["target_price"] = target_series.shift(1).fillna(close_series)
        df["enter_signal"] = enter_series.shift(1).fillna(False).astype(bool)
        df["exit_signal"] = exit_series.shift(1).fillna(False).astype(bool)

        return df

    def _use_vectorized_path(self) -> bool:
        if self.signal_builder is not None:
            return False
        signal_context_builder = getattr(self._build_signal_context, "__func__", None)
        return signal_context_builder is Backtester._build_signal_context

    def run(
        self,
        ticker: str,
        df: pd.DataFrame,
        verbose: bool = True,
        output_path: str | Path | None = None,
    ) -> Optional[BacktestResult]:
        if df is None or len(df) < 50:
            logger.warning(f"  Yetersiz veri: {len(df) if df is not None else 0}")
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

        if result is not None and output_path is not None:
            result.to_json(output_path)
        return result

    def _run_vectorized(
        self,
        ticker: str,
        df: pd.DataFrame,
        verbose: bool,
    ) -> Optional[BacktestResult]:
        df = self._precalculate_signals(df)

        capital = self.initial_capital
        position: Optional[dict[str, Any]] = None
        trades: list[BacktestTrade] = []
        capital_history: list[float] = [capital]
        last_buy_date: Optional[datetime] = None

        for i, row in enumerate(df.itertuples(index=False, name="Bar")):
            date = _to_datetime(df.index[i])
            open_price = _to_float(getattr(row, "open", getattr(row, "close", 0.0)), _to_float(getattr(row, "close", 0.0)))
            high_price = _to_float(getattr(row, "high", open_price), open_price)
            low_price = _to_float(getattr(row, "low", open_price), open_price)
            close_price = _to_float(getattr(row, "close", open_price), open_price)

            signal = {
                "enter": bool(getattr(row, "enter_signal", False)),
                "exit": bool(getattr(row, "exit_signal", False)),
                "score": _to_float(getattr(row, "score", 0.0), 0.0),
                "stop_loss": _to_float(getattr(row, "calculated_stop", close_price * 0.95), close_price * 0.95),
                "target_price": _to_float(getattr(row, "target_price", close_price), close_price),
            }

            if position is not None and self._should_exit_on_open(signal):
                exit_fill_price = self._calculate_dynamic_slippage(open_price, row, is_buy=False)
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
                    entry_fill_price = self._calculate_dynamic_slippage(open_price, row, is_buy=True)
                    position = self._open_position(signal, entry_fill_price, date, capital)
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
                intrabar_exit = self._simulate_intrabar_exit(position, open_price, high_price, low_price, close_price)
                if intrabar_exit is not None:
                    ref_price = intrabar_exit["reference_price"]
                    exit_fill_price = self._calculate_dynamic_slippage(ref_price, row, is_buy=False)
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

            equity = capital if position is None else capital + position["shares"] * close_price
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
                fill_price=self._calculate_dynamic_slippage(last_close, last_bar, is_buy=False),
                reference_price=last_close,
                reason="FINAL_CLOSE",
                verbose=False,
            )
            capital_history[-1] = capital

        return self._build_result(ticker, df, capital, trades, capital_history)

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
                exit_fill_price = self._calculate_dynamic_slippage(open_price, bar, is_buy=False)
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
                    entry_fill_price = self._calculate_dynamic_slippage(open_price, bar, is_buy=True)
                    position = self._open_position(signal, entry_fill_price, date, capital)
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
                intrabar_exit = self._simulate_intrabar_exit(position, open_price, high_price, low_price, close_price)
                if intrabar_exit is not None:
                    ref_price = intrabar_exit["reference_price"]
                    exit_fill_price = self._calculate_dynamic_slippage(ref_price, bar, is_buy=False)
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

            equity = capital if position is None else capital + position["shares"] * close_price
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
                fill_price=self._calculate_dynamic_slippage(last_close, last_bar, is_buy=False),
                reference_price=last_close,
                reason="FINAL_CLOSE",
                verbose=False,
            )
            capital_history[-1] = capital

        return self._build_result(ticker, df, capital, trades, capital_history)

    def _build_signal_context(self, ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
        if self.signal_builder is not None:
            return self.signal_builder(ticker, history)
        score = self._calculate_score(history)
        last_close = _to_float(history.iloc[-1].get("close"))
        stop_loss = _to_float(history.iloc[-1].get("stop_loss_atr"), last_close * 0.95)
        risk_per_share = max(last_close - stop_loss, last_close * 0.01)
        target_price = max(last_close + risk_per_share * self.target_rr, last_close)
        return {
            "enter": score >= self.buy_threshold,
            "exit": score <= self.sell_threshold,
            "score": score,
            "stop_loss": stop_loss,
            "target_price": target_price,
        }

    def _should_enter_on_open(self, signal: dict[str, float | bool]) -> bool:
        return bool(signal.get("enter"))

    def _should_exit_on_open(self, signal: dict[str, float | bool]) -> bool:
        return bool(signal.get("exit"))

    def _calculate_dynamic_slippage(self, price: float, row: Any, is_buy: bool) -> float:
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
        entry_date: datetime,
        capital: float,
    ) -> Optional[dict[str, Any]]:
        entry_price = fill_price
        unit_cost = entry_price * (1 + self.commission_buy_pct)
        shares = int(capital / unit_cost) if unit_cost > 0 else 0
        if shares <= 0:
            return None

        cost = shares * unit_cost
        return {
            "entry_date": entry_date,
            "entry_price": entry_price,
            "shares": shares,
            "cost": cost,
            "stop_loss": _to_float(signal.get("stop_loss"), entry_price * 0.95),
            "target_price": _to_float(signal.get("target_price"), 0.0),
            "score": _to_float(signal.get("score"), 0.0),
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
            stop_first = close_price >= open_price
            first_reason = "STOP_LOSS" if stop_first else "TAKE_PROFIT"
            first_price = stop_loss if stop_first else target_price
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
        revenue = position["shares"] * fill_price * (1 - self.commission_sell_pct)
        profit_tl = revenue - position["cost"]
        profit_pct = (profit_tl / position["cost"]) * 100 if position["cost"] else 0.0
        holding_days = max((exit_date - position["entry_date"]).days, 0)

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
            )
        )

        if verbose:
            emoji = "✅" if profit_tl > 0 else "❌"
            logger.info(
                f"  🔴 SAT ({reason}): {exit_date.strftime('%d.%m')} | "
                f"₺{reference_price:.2f} -> ₺{fill_price:.2f} | "
                f"{emoji} {profit_pct:+.1f}% (₺{profit_tl:+.0f}) | {holding_days} gün"
            )

        return capital + revenue

    def _build_result(
        self,
        ticker: str,
        df: pd.DataFrame,
        capital: float,
        trades: list[BacktestTrade],
        capital_history: list[float],
    ) -> BacktestResult:
        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        winning = [t for t in trades if t.profit_pct > 0]
        losing = [t for t in trades if t.profit_pct <= 0]

        cap_series = pd.Series(capital_history, dtype=float)
        rolling_max = cap_series.cummax()
        drawdown = (cap_series - rolling_max) / rolling_max * 100
        max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

        sharpe = 0.0
        if len(trades) > 1:
            returns = np.array([t.profit_pct for t in trades], dtype=float)
            std = float(np.std(returns))
            if std > 0:
                sharpe = float(np.mean(returns) / std * np.sqrt(252))

        avg_holding = 0.0
        idle_ratio = 0.0
        if trades:
            holding_days = [t.holding_days for t in trades]
            avg_holding = round(float(np.mean(holding_days)), 1)
            total_days = (_to_datetime(df.index[-1]) - _to_datetime(df.index[0])).days
            if total_days > 0:
                idle_ratio = round((total_days - sum(holding_days)) / total_days * 100, 1)

        self.avg_holding_days = avg_holding
        logger.info(f"  📊 Ort. holding: {avg_holding} gün, Idle: %{idle_ratio}")

        return BacktestResult(
            ticker=ticker,
            period=f"{_to_datetime(df.index[0]).strftime('%d.%m.%Y')} → {_to_datetime(df.index[-1]).strftime('%d.%m.%Y')}",
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            total_return_pct=round(total_return, 2),
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=round(len(winning) / len(trades) * 100, 1) if trades else 0.0,
            avg_profit_pct=round(float(np.mean([t.profit_pct for t in winning])), 2) if winning else 0.0,
            avg_loss_pct=round(float(np.mean([t.profit_pct for t in losing])), 2) if losing else 0.0,
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            trades=trades,
        )

    def _calculate_score(self, df: pd.DataFrame) -> float:
        if len(df) < 2:
            return 0.0

        last = df.iloc[-1]
        score = 0.0

        rsi = last.get("rsi")
        if pd.notna(rsi):
            if rsi < settings.RSI_OVERSOLD:
                score += 20
            elif rsi > settings.RSI_OVERBOUGHT:
                score -= 20

        sma_cross = last.get("sma_cross", "NONE")
        if sma_cross == "GOLDEN_CROSS":
            score += 20
        elif sma_cross == "DEATH_CROSS":
            score -= 20

        sma_fast = last.get(f"sma_{settings.SMA_FAST}")
        sma_slow = last.get(f"sma_{settings.SMA_SLOW}")
        if pd.notna(sma_fast) and pd.notna(sma_slow):
            score += 5 if float(sma_fast) > float(sma_slow) else -5

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

        return max(-100.0, min(100.0, score))


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

    def run(self, ticker: str, df: pd.DataFrame, verbose: bool = False) -> Optional[BacktestResult]:
        self._enriched_cache = TechnicalIndicators().add_all(df.copy())

        def signal_builder(ticker: str, history: pd.DataFrame) -> dict[str, float | bool]:
            idx = len(history) - 1
            if self._enriched_cache is None or idx < 0 or idx >= len(self._enriched_cache):
                return self._empty_signal_context()

            enriched_slice = self._enriched_cache.iloc[: idx + 1]
            signal = self.engine.analyze(ticker, enriched_slice, enforce_sector_limit=False)
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


def _reload_strategy_dependencies() -> StrategyEngineProtocol:
    reloaded_module = importlib.reload(strategy_module)
    return reloaded_module.StrategyEngine()


if __name__ == "__main__":
    from data_fetcher import BISTDataFetcher

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


def generate_report(result: BacktestResult, benchmark_return: Optional[float] = None) -> str:
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
        logger.warning(f"Benchmark veri hatası: {e}")
    return 0.0
