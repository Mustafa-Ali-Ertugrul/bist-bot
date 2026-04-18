import json
from pathlib import Path

import numpy as np
import pandas as pd

import config
from backtest import Backtester, _to_datetime, _to_float
from data_fetcher import BISTDataFetcher


class TraceBacktester(Backtester):
    def run_with_trace(self, ticker, df):
        if df is None or len(df) < 50:
            return None
        df = self.indicators.add_all(df.copy())
        df = df.dropna(subset=["rsi", f"sma_{config.SMA_SLOW}"])
        if len(df) < 2:
            return None

        capital = self.initial_capital
        position = None
        trades = []
        capital_history = [capital]
        equity_dates = [_to_datetime(df.index[0])]
        last_buy_date = None

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
                capital = self._close_position(
                    capital,
                    position,
                    trades,
                    ticker,
                    date,
                    self._apply_sell_slippage(open_price),
                    open_price,
                    "SIGNAL_OPEN",
                    False,
                )
                position = None

            if position is None and self._should_enter_on_open(signal):
                if last_buy_date is None or (date - last_buy_date).days >= 1:
                    position = self._open_position(signal, open_price, date, capital)
                    if position is not None:
                        capital -= position["cost"]
                        last_buy_date = date

            if position is not None:
                intrabar_exit = self._simulate_intrabar_exit(
                    position, open_price, high_price, low_price, close_price
                )
                if intrabar_exit is not None:
                    capital = self._close_position(
                        capital,
                        position,
                        trades,
                        ticker,
                        date,
                        intrabar_exit["fill_price"],
                        intrabar_exit["reference_price"],
                        intrabar_exit["reason"],
                        False,
                    )
                    position = None

            equity = capital if position is None else capital + position["shares"] * close_price
            capital_history.append(equity)
            equity_dates.append(date)

        if position is not None:
            last_date = _to_datetime(df.index[-1])
            last_close = _to_float(df.iloc[-1].get("close"))
            capital = self._close_position(
                capital,
                position,
                trades,
                ticker,
                last_date,
                self._apply_sell_slippage(last_close),
                last_close,
                "FINAL_CLOSE",
                False,
            )
            capital_history[-1] = capital
            equity_dates[-1] = last_date

        result = self._build_result(ticker, df, capital, trades, capital_history)
        cap_series = pd.Series(capital_history, index=pd.to_datetime(equity_dates), dtype=float)
        drawdown = (cap_series - cap_series.cummax()) / cap_series.cummax() * 100
        dd_date = drawdown.idxmin() if not drawdown.empty else None
        return result, dd_date


def main() -> None:
    src = Path("data/watchlist_backtest_results.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data["results"]
    eligible = [r for r in rows if int(r.get("total_trades", 0)) >= 10]
    excluded = [r for r in rows if int(r.get("total_trades", 0)) < 10]

    min_sh = min(r["sharpe_ratio"] for r in eligible)
    max_sh = max(r["sharpe_ratio"] for r in eligible)
    min_wr = min(r["win_rate"] for r in eligible)
    max_wr = max(r["win_rate"] for r in eligible)
    dd_abs = [abs(r["max_drawdown_pct"]) for r in eligible]
    min_dd = min(dd_abs)
    max_dd = max(dd_abs)

    for row in eligible:
        sharpe_component = (row["sharpe_ratio"] - min_sh) / (max_sh - min_sh) if max_sh > min_sh else 0.0
        win_rate_component = (row["win_rate"] - min_wr) / (max_wr - min_wr) if max_wr > min_wr else 0.0
        drawdown_component = (max_dd - abs(row["max_drawdown_pct"])) / (max_dd - min_dd) if max_dd > min_dd else 0.0
        row["composite_score"] = round(
            (0.4 * sharpe_component + 0.3 * win_rate_component + 0.3 * drawdown_component) * 100,
            2,
        )

    eligible.sort(key=lambda r: (r["composite_score"], r["sharpe_ratio"], r["win_rate"]), reverse=True)
    top10 = eligible[:10]
    false_positives = sorted(
        [row for row in excluded if row["sharpe_ratio"] >= 10],
        key=lambda row: row["sharpe_ratio"],
        reverse=True,
    )

    fetcher = BISTDataFetcher()
    backtester = TraceBacktester(initial_capital=getattr(config, "INITIAL_CAPITAL", 8500.0))
    details = []

    for item in top10:
        ticker = item["ticker"]
        df = fetcher.fetch_single(ticker, period="1y", interval="1d")
        traced = backtester.run_with_trace(ticker, df) if df is not None else None
        if traced is None:
            continue

        result, dd_date = traced
        wins = [trade.profit_pct for trade in result.trades if trade.profit_pct > 0]
        losses = [abs(trade.profit_pct) for trade in result.trades if trade.profit_pct <= 0]
        gross_profit = sum(trade.profit_tl for trade in result.trades if trade.profit_tl > 0)
        gross_loss = abs(sum(trade.profit_tl for trade in result.trades if trade.profit_tl < 0))
        profit_factor = "N/A" if gross_loss == 0 else round(gross_profit / gross_loss, 2)

        details.append(
            {
                "ticker": ticker,
                "name": config.TICKER_NAMES.get(ticker, ticker.replace(".IS", "")),
                "total_trades": result.total_trades,
                "annual_return_pct": round(result.total_return_pct, 2),
                "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                "max_drawdown_date": dd_date.strftime("%d.%m.%Y") if dd_date is not None else "N/A",
                "avg_win_pct": round(float(np.mean(wins)), 2) if wins else 0.0,
                "avg_loss_pct": round(float(np.mean(losses)), 2) if losses else 0.0,
                "profit_factor": profit_factor,
                "composite_score": item["composite_score"],
            }
        )

    lines = [
        "# Top 10 Significant Backtest Report",
        "",
        "Bu rapor, en az 10 islem yapan hisseler arasinda Kompozit Skor (%40 Sharpe, %30 Win Rate, %30 dusuk Max Drawdown) ile secilen ilk 10 hisseyi ozetler.",
        "",
        "## Filtrelenmis En Iyi 10 Hisse",
        "",
        "| Hisse | Composite Score | Toplam Islem | Yillik Getiri % | Max DD | Max DD Tarihi | Ort. Kazanan % | Ort. Kaybeden % | Profit Factor |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]

    for detail in details:
        lines.append(
            f"| {detail['name']} ({detail['ticker']}) | {detail['composite_score']:.2f} | {detail['total_trades']} | {detail['annual_return_pct']:.2f} | {detail['max_drawdown_pct']:.2f} | {detail['max_drawdown_date']} | {detail['avg_win_pct']:.2f} | {detail['avg_loss_pct']:.2f} | {detail['profit_factor']} |"
        )

    lines.extend(["", "## Hisse Bazli Detaylar", ""])
    for detail in details:
        lines.extend(
            [
                f"### {detail['name']} ({detail['ticker']})",
                f"- Toplam Islem Sayisi: {detail['total_trades']}",
                f"- Yillik Getiri: %{detail['annual_return_pct']:.2f}",
                f"- Maximum Drawdown: %{detail['max_drawdown_pct']:.2f} (`{detail['max_drawdown_date']}`)",
                f"- Ortalama Kazanan Islem: %{detail['avg_win_pct']:.2f}",
                f"- Ortalama Kaybeden Islem: %{detail['avg_loss_pct']:.2f}",
                f"- Profit Factor: `{detail['profit_factor']}`",
                f"- Kompozit Skor: `{detail['composite_score']:.2f}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Dikkat: Dusuk Islem Sayili Potansiyel Yalanci Pozitifler",
            "",
            "Asagidaki hisseler yuksek Sharpe skoruna ragmen 10 islem esiginin altinda kaldigi icin ana listeye alinmadi.",
            "",
        ]
    )

    if false_positives:
        lines.extend(
            [
                "| Hisse | Sharpe | Toplam Islem | Win Rate | Max DD |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in false_positives:
            name = config.TICKER_NAMES.get(row["ticker"], row["ticker"].replace(".IS", ""))
            lines.append(
                f"| {name} ({row['ticker']}) | {row['sharpe_ratio']:.2f} | {row['total_trades']} | {row['win_rate']:.1f} | {row['max_drawdown_pct']:.2f} |"
            )
    else:
        lines.append("- Esik ustu dikkat ceken yalanci pozitif bulunmadi.")

    out = Path("data/top10_significant_report.md")
    out.write_text("\n".join(lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "top10": [
                    {
                        "ticker": detail["ticker"],
                        "composite_score": detail["composite_score"],
                        "total_trades": detail["total_trades"],
                    }
                    for detail in details
                ],
                "false_positives": [row["ticker"] for row in false_positives],
                "output": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
