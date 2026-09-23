"""Prototype: BIST Alpha Trend Strategy (Institutional Momentum & Relative Strength)

Core principles:
1. Macro Hard-Gate: XU100 > SMA50 (No longs in market correction/bear).
2. Relative Strength: Stock outperforming XU100 (RS > SMA20(RS) and RS rising).
3. Volume Expansion: Volume > 1.5x 20-day volume SMA.
4. Clean Breakout: 20-day high breakout with strong close (upper 30% of day's range).
5. Asymmetric Risk: Initial stop 1.5 ATR (max 5%), Exit on Trailing Stop
   (2.5 ATR from peak close). No fixed profit cap.

Round-2 fix note: the trade simulation in this module is DELEGATED to the
shared causal simulator (``bist_bot.backtest.alpha_trend_sim``). The
original local exit loop had an intrabar look-ahead bias (trailing stop
derived from the current bar's close, then tested against the same bar's
low) and never tested the entry bar against the initial stop; both are
fixed in the shared engine. ``Trade`` and ``fetch_or_load`` remain
importable from here for backward compatibility.
"""

from __future__ import annotations

from bist_bot.backtest.alpha_trend_sim import (
    SimTrade as Trade,
)
from bist_bot.backtest.alpha_trend_sim import (
    preload_all,
    run_trades,
    trade_stats,
)


def run_alpha_backtest(
    tickers: list[str],
    period: str = "2y",
    trail_mult: float = 2.5,
    max_stop_pct: float = 5.0,
    cost_roundtrip_pct: float = 0.35,  # 0.20% commission + 0.15% slippage
) -> dict[str, object]:
    print("--- Fetching benchmark (XU100.IS) ---")
    xu100, cache = preload_all(tickers, period=period)
    print(f"--- Running Alpha Screen on {len(tickers)} tickers ---")
    trades = run_trades(xu100, cache, trail_mult, max_stop_pct, cost_roundtrip_pct)
    stats: dict[str, object] = trade_stats(trades)
    stats["trades"] = trades
    return stats


def main():
    # Test on BIST30 first
    bist30 = [
        "AKBNK.IS",
        "ALARK.IS",
        "ASELS.IS",
        "ASTOR.IS",
        "BIMAS.IS",
        "BRSAN.IS",
        "DOAS.IS",
        "EKGYO.IS",
        "ENKAI.IS",
        "EREGL.IS",
        "FROTO.IS",
        "GARAN.IS",
        "GUBRF.IS",
        "HEKTS.IS",
        "ISCTR.IS",
        "KCHOL.IS",
        "KONTR.IS",
        "KOZAL.IS",
        "KRDMD.IS",
        "ODAS.IS",
        "OYAKC.IS",
        "PETKM.IS",
        "PGSUS.IS",
        "SAHOL.IS",
        "SASA.IS",
        "SISE.IS",
        "TCELL.IS",
        "THYAO.IS",
        "TOASO.IS",
        "TUPRS.IS",
        "YKBNK.IS",
    ]

    print("==================================================================")
    print("TEST 1: BIST30 Alpha Trend (Relative Strength + Volume + Trail 2.5)")
    print("==================================================================")
    res30 = run_alpha_backtest(bist30, period="2y", trail_mult=2.5)
    print(f"Trades: {res30['n']}")
    print(f"Win Rate: {res30['win_rate']}%")
    print(f"Profit Factor: {res30['profit_factor']}")
    print(f"Avg Net Return: {res30['avg_net_pp']} pp per trade")
    print(f"Avg Winner: {res30['avg_win_pp']} pp | Avg Loser: {res30['avg_loss_pp']} pp")

    trades: list[Trade] = res30.get("trades", [])  # type: ignore[assignment]
    if trades:
        print("\nTop 5 Winners:")
        for t in sorted(trades, key=lambda x: x.net_pnl_pct, reverse=True)[:5]:
            print(
                f"  {t.ticker:10} {t.entry_date.strftime('%Y-%m-%d')} -> {t.exit_date.strftime('%Y-%m-%d')} "
                f"({t.holding_bars:>2} bars) Net: {t.net_pnl_pct:+.2f}% [{t.exit_reason}]"
            )
        print("\nTop 5 Losers:")
        for t in sorted(trades, key=lambda x: x.net_pnl_pct)[:5]:
            print(
                f"  {t.ticker:10} {t.entry_date.strftime('%Y-%m-%d')} -> {t.exit_date.strftime('%Y-%m-%d')} "
                f"({t.holding_bars:>2} bars) Net: {t.net_pnl_pct:+.2f}% [{t.exit_reason}]"
            )


if __name__ == "__main__":
    main()
