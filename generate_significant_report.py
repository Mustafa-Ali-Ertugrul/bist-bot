import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from backtest import Backtester, _to_datetime, _to_float
from data_fetcher import BISTDataFetcher


SPARKLINE_CHARS = ".-:=+*#%@"


class TraceBacktester(Backtester):
    def run_with_trace(self, ticker, df):
        if df is None or len(df) < 50:
            return None
        df = self.indicators.add_all(df.copy())
        df = df.dropna(subset=["rsi", f"sma_{settings.SMA_SLOW}"])
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


def compute_composite_scores(rows):
    min_sh = min(r["sharpe_ratio"] for r in rows)
    max_sh = max(r["sharpe_ratio"] for r in rows)
    min_wr = min(r["win_rate"] for r in rows)
    max_wr = max(r["win_rate"] for r in rows)
    dd_abs = [abs(r["max_drawdown_pct"]) for r in rows]
    min_dd = min(dd_abs)
    max_dd = max(dd_abs)

    scored = []
    for row in rows:
        item = dict(row)
        sharpe_component = (item["sharpe_ratio"] - min_sh) / (max_sh - min_sh) if max_sh > min_sh else 0.0
        win_rate_component = (item["win_rate"] - min_wr) / (max_wr - min_wr) if max_wr > min_wr else 0.0
        drawdown_component = (max_dd - abs(item["max_drawdown_pct"])) / (max_dd - min_dd) if max_dd > min_dd else 0.0
        item["composite_score"] = round(
            (0.4 * sharpe_component + 0.3 * win_rate_component + 0.3 * drawdown_component) * 100,
            2,
        )
        scored.append(item)

    scored.sort(key=lambda r: (r["composite_score"], r["sharpe_ratio"], r["win_rate"]), reverse=True)
    return scored


def build_detail(fetcher, backtester, item):
    ticker = item["ticker"]
    df = fetcher.fetch_single(ticker, period="1y", interval="1d")
    traced = backtester.run_with_trace(ticker, df) if df is not None else None
    if traced is None:
        return None

    result, dd_date = traced
    wins = [trade.profit_pct for trade in result.trades if trade.profit_pct > 0]
    losses = [abs(trade.profit_pct) for trade in result.trades if trade.profit_pct <= 0]
    gross_profit = sum(trade.profit_tl for trade in result.trades if trade.profit_tl > 0)
    gross_loss = abs(sum(trade.profit_tl for trade in result.trades if trade.profit_tl < 0))
    profit_factor = "N/A" if gross_loss == 0 else round(gross_profit / gross_loss, 2)

    close_values = df["close"].astype(float).tolist() if "close" in df.columns else []

    return {
        "ticker": ticker,
        "name": settings.TICKER_NAMES.get(ticker, ticker.replace(".IS", "")),
        "total_trades": result.total_trades,
        "annual_return_pct": round(result.total_return_pct, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "max_drawdown_date": dd_date.strftime("%d.%m.%Y") if dd_date is not None else "N/A",
        "avg_win_pct": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss_pct": round(float(np.mean(losses)), 2) if losses else 0.0,
        "profit_factor": profit_factor,
        "composite_score": item["composite_score"],
        "sparkline": build_ascii_sparkline(close_values),
    }


def profit_factor_value(detail):
    return float(detail["profit_factor"]) if detail["profit_factor"] != "N/A" else 0.0


def build_ascii_sparkline(values, width=18):
    if not values:
        return "n/a"
    if len(values) <= width:
        sample = values
    else:
        positions = np.linspace(0, len(values) - 1, width)
        sample = [values[int(pos)] for pos in positions]

    low = min(sample)
    high = max(sample)
    if high <= low:
        return "-" * len(sample)

    scale = len(SPARKLINE_CHARS) - 1
    chars = []
    for value in sample:
        normalized = (value - low) / (high - low)
        index = min(scale, max(0, int(round(normalized * scale))))
        chars.append(SPARKLINE_CHARS[index])
    return "".join(chars)


def add_star_ratings(details):
    if not details:
        return details
    min_score = min(detail["composite_score"] for detail in details)
    max_score = max(detail["composite_score"] for detail in details)
    for detail in details:
        if max_score == min_score:
            stars = 5
        else:
            normalized = (detail["composite_score"] - min_score) / (max_score - min_score)
            stars = 1 + int(round(normalized * 4))
        detail["star_rating"] = "*" * stars + "-" * (5 - stars)
    return details


def write_significant_report(details, false_positives):
    details = add_star_ratings(details)
    avg_return = round(sum(d["annual_return_pct"] for d in details) / len(details), 2)
    avg_drawdown = round(sum(d["max_drawdown_pct"] for d in details) / len(details), 2)
    avg_trades = round(sum(d["total_trades"] for d in details) / len(details), 1)
    best_pf = max(details, key=profit_factor_value)

    lines = [
        "# Top 10 Significant Backtest Report",
        "",
        "## Yonetici Ozeti",
        "",
        f"Bu strateji, filtrelenmis 10 hissede yillik ortalama `%{avg_return:.2f}` getiri, ortalama `%{avg_drawdown:.2f}` maksimum dusus ve ortalama `{avg_trades:.1f}` islem ile calisti. En verimli hisse `{best_pf['name']} ({best_pf['ticker']})` olup Profit Factor degeri `{best_pf['profit_factor']}` oldu.",
        "",
        "| Ortalama Yillik Getiri % | Ortalama Risk (Max DD %) | Ortalama Islem Sayisi | En Yuksek Profit Factor |",
        "| ---: | ---: | ---: | --- |",
        f"| {avg_return:.2f} | {avg_drawdown:.2f} | {avg_trades:.1f} | {best_pf['name']} ({best_pf['ticker']}): {best_pf['profit_factor']} |",
        "",
        "Bu rapor, en az 10 islem yapan hisseler arasinda Kompozit Skor (%40 Sharpe, %30 Win Rate, %30 dusuk Max Drawdown) ile secilen ilk 10 hisseyi ozetler.",
        "",
        "## Filtrelenmis En Iyi 10 Hisse",
        "",
        "| Hisse | Yildiz | Composite Score | Toplam Islem | Yillik Getiri % | Max DD | Max DD Tarihi | Profit Factor | Trend |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]

    for detail in details:
        lines.append(
            f"| {detail['name']} ({detail['ticker']}) | `{detail['star_rating']}` | {detail['composite_score']:.2f} | {detail['total_trades']} | {detail['annual_return_pct']:.2f} | {detail['max_drawdown_pct']:.2f} | {detail['max_drawdown_date']} | {detail['profit_factor']} | `{detail['sparkline']}` |"
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
                f"- Yildiz Puani: `{detail['star_rating']}`",
                f"- Mini Trend: `{detail['sparkline']}`",
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
            name = settings.TICKER_NAMES.get(row["ticker"], row["ticker"].replace(".IS", ""))
            lines.append(
                f"| {name} ({row['ticker']}) | {row['sharpe_ratio']:.2f} | {row['total_trades']} | {row['win_rate']:.1f} | {row['max_drawdown_pct']:.2f} |"
            )
    else:
        lines.append("- Esik ustu dikkat ceken yalanci pozitif bulunmadi.")

    out = Path("data/top10_significant_report.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_strict_report(strict_details, risky_candidates):
    lines = [
        "# Strict Profitable Watchlist",
        "",
        "> Bu liste, hem istatistiksel olarak anlamli (yeterli veri) hem de gecmiste karli kapanmis hisseleri icerir. Canli islem icin en dusuk riskli havuzdur.",
        "",
        "## Strict Mode Listesi",
        "",
        "| Hisse | Composite Score | Toplam Islem | Yillik Getiri % | Max DD | Max DD Tarihi | Ort. Kazanan % | Ort. Kaybeden % | Profit Factor |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]

    for detail in strict_details:
        lines.append(
            f"| {detail['name']} ({detail['ticker']}) | {detail['composite_score']:.2f} | {detail['total_trades']} | {detail['annual_return_pct']:.2f} | {detail['max_drawdown_pct']:.2f} | {detail['max_drawdown_date']} | {detail['avg_win_pct']:.2f} | {detail['avg_loss_pct']:.2f} | {detail['profit_factor']} |"
        )

    lines.extend(["", "## Riskli Ancak Potansiyelli", ""])
    if risky_candidates:
        lines.extend(
            [
                "Top 10 listesine girip pozitif getiri kosulunu saglayamadigi icin elenen hisseler:",
                "",
                "| Hisse | Composite Score | Toplam Islem | Yillik Getiri % | Sharpe | Max DD |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in risky_candidates:
            lines.append(
                f"| {item['name']} ({item['ticker']}) | {item['composite_score']:.2f} | {item['total_trades']} | {item['annual_return_pct']:.2f} | {item['sharpe_ratio']:.2f} | {item['max_drawdown_pct']:.2f} |"
            )
    else:
        lines.append("- Top 10 listesinden negatif getiri nedeniyle elenen hisse yok.")

    out = Path("data/strict_profitable_watchlist.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    src = Path("data/watchlist_backtest_results.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data["results"]
    eligible = [r for r in rows if int(r.get("total_trades", 0)) >= 10]
    excluded = [r for r in rows if int(r.get("total_trades", 0)) < 10]

    eligible = compute_composite_scores(eligible)
    top10 = eligible[:10]
    false_positives = sorted(
        [row for row in excluded if row["sharpe_ratio"] >= 10],
        key=lambda row: row["sharpe_ratio"],
        reverse=True,
    )

    fetcher = BISTDataFetcher()
    backtester = TraceBacktester(initial_capital=getattr(settings, "INITIAL_CAPITAL", 8500.0))
    details = []

    for item in top10:
        detail = build_detail(fetcher, backtester, item)
        if detail is not None:
            details.append(detail)

    out = write_significant_report(details, false_positives)

    strict_candidates = [row for row in eligible if row["total_return_pct"] > 0]
    strict_top10 = strict_candidates[:10]
    strict_details = []
    for item in strict_top10:
        detail = build_detail(fetcher, backtester, item)
        if detail is not None:
            strict_details.append(detail)

    risky_candidates = []
    top10_tickers = {row["ticker"] for row in top10}
    strict_tickers = {row["ticker"] for row in strict_top10}
    for row in eligible:
        if row["ticker"] in top10_tickers and row["ticker"] not in strict_tickers:
            risky_candidates.append(
                {
                    "ticker": row["ticker"],
                    "name": settings.TICKER_NAMES.get(row["ticker"], row["ticker"].replace(".IS", "")),
                    "composite_score": row["composite_score"],
                    "total_trades": row["total_trades"],
                    "annual_return_pct": row["total_return_pct"],
                    "sharpe_ratio": row["sharpe_ratio"],
                    "max_drawdown_pct": row["max_drawdown_pct"],
                }
            )

    strict_out = write_strict_report(strict_details, risky_candidates)

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
                "strict_output": str(strict_out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
