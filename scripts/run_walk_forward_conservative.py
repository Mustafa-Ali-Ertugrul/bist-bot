"""Run day-based walk-forward validation with StrategyParams.conservative().

Usage (from repo root):
    python scripts/run_walk_forward_conservative.py
"""

from __future__ import annotations

import warnings

import yfinance as yf

from bist_bot.strategy.params import StrategyParams
from bist_bot.validation import WalkForwardValidator

warnings.filterwarnings("ignore")


def _normalize_ohlcv(df):
    if df is None or df.empty:
        return df
    out = df.copy()
    if getattr(out.columns, "nlevels", 1) > 1:
        out.columns = [
            c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in out.columns
        ]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename = {}
    for c in list(out.columns):
        if c in {"adj close", "adj_close"}:
            rename[c] = "close"
    if rename:
        out = out.rename(columns=rename)
    return out


def main() -> None:
    params = StrategyParams.conservative()
    wf = WalkForwardValidator(
        train_window=252,
        test_window=63,
        step_size=63,
        commission_bps=2.0,
        slippage_bps=5.0,
        initial_capital=100_000.0,
        strategy_params=params,
    )

    tickers = ["THYAO.IS", "GARAN.IS", "ASELS.IS"]
    rows: list[dict[str, object]] = []

    print("Profile: StrategyParams.conservative()")
    print(
        f"  buy_threshold={params.buy_threshold}  sell_threshold={params.sell_threshold}  "
        f"sideways_mult={params.sideways_score_multiplier}  "
        f"rsi_extreme={params.score_rsi_extreme}  stoch_cross={params.score_stoch_cross}"
    )
    print(
        f"WF: train={wf.train_window} test={wf.test_window} step={wf.step_size}  "
        f"commission_bps={wf.commission_bps} slippage_bps={wf.slippage_bps}"
    )
    print("=" * 88)

    for ticker in tickers:
        print(f"Downloading {ticker} ...")
        raw = yf.download(ticker, period="3y", auto_adjust=True, progress=False)
        df = _normalize_ohlcv(raw)
        if df is None or df.empty:
            print(f"{ticker}: NO DATA")
            rows.append(
                {
                    "ticker": ticker,
                    "windows": 0,
                    "is_mean": None,
                    "oos_mean": None,
                    "oos_dd": None,
                    "oos_sharpe": None,
                    "overfit": "NO_DATA",
                }
            )
            continue

        result = wf.run(ticker, df)
        if result is None:
            print(f"{ticker}: insufficient history for walk-forward windows")
            rows.append(
                {
                    "ticker": ticker,
                    "windows": 0,
                    "is_mean": None,
                    "oos_mean": None,
                    "oos_dd": None,
                    "oos_sharpe": None,
                    "overfit": "NO_WINDOWS",
                }
            )
            continue

        is_mean = result.is_aggregate["mean_total_return_pct"]
        oos_mean = result.oos_aggregate["mean_total_return_pct"]
        oos_dd = result.oos_aggregate["mean_max_drawdown_pct"]
        oos_sharpe = result.oos_aggregate["mean_sharpe_ratio"]
        flag = "YES" if result.has_overfitting_warning else "no"
        rows.append(
            {
                "ticker": ticker,
                "windows": len(result.windows),
                "is_mean": is_mean,
                "oos_mean": oos_mean,
                "oos_dd": oos_dd,
                "oos_sharpe": oos_sharpe,
                "overfit": flag,
            }
        )
        print(
            f"{ticker}: windows={len(result.windows)}  "
            f"IS={is_mean:.2f}%  OOS={oos_mean:.2f}%  "
            f"OOS_DD={oos_dd:.2f}%  OOS_Sharpe={oos_sharpe:.3f}  overfit={flag}"
        )
        rets = [f"{w.test_return_pct:.1f}%" for w in result.windows]
        print(f"  OOS per-window: {rets}")

    print("=" * 88)
    print(
        f"{'Ticker':<12} {'Win':>4} {'IS mean%':>10} {'OOS mean%':>10} "
        f"{'OOS DD%':>10} {'OOS Sharpe':>11} {'Overfit':>8}"
    )
    print("-" * 88)
    for row in rows:
        if row["is_mean"] is None:
            print(
                f"{row['ticker']:<12} {row['windows']:>4} {'n/a':>10} {'n/a':>10} "
                f"{'n/a':>10} {'n/a':>11} {row['overfit']!s:>8}"
            )
        else:
            print(
                f"{row['ticker']:<12} {row['windows']:>4} "
                f"{row['is_mean']:>10.2f} {row['oos_mean']:>10.2f} "
                f"{row['oos_dd']:>10.2f} {row['oos_sharpe']:>11.3f} "
                f"{row['overfit']!s:>8}"
            )
    print("=" * 88)
    print("DONE")


if __name__ == "__main__":
    main()
