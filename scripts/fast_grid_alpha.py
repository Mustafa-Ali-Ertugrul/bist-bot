"""Fast in-memory grid search for BIST Alpha Trend Strategy.

Trade simulation is DELEGATED to the shared causal simulator
(``bist_bot.backtest.alpha_trend_sim``). The historical local exit loop
was removed in the Round-2 intrabar look-ahead fix: it derived each
bar's trailing stop from that bar's own close and tested the same
bar's low against it, inflating PF from ~1.001 (causal) to 1.428.
"""

from __future__ import annotations

from bist_bot.backtest.alpha_trend_sim import (
    evaluate,
    preload_all,
)


def main():
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
    print("Preloading cached data...")
    xu100, cache = preload_all(bist30, period="2y")
    print(f"Loaded {len(cache)} tickers successfully.")

    print(
        f"\n{'Trail Mult':<12} {'Max Stop':<10} {'Trades':<8} {'Win Rate':<10} "
        f"{'PF':<8} {'Avg Net':<10} {'Avg Win':<10} {'Avg Loss':<10}"
    )
    print("=" * 80)

    for trail in [2.0, 2.5, 3.0, 3.5]:
        for max_stop in [4.0, 5.0, 6.0]:
            res = evaluate(xu100, cache, trail_mult=trail, max_stop_pct=max_stop)
            print(
                f"{trail:<12.1f} {max_stop:<10.1f} {res['n']:<8} {res['win_rate']:<9.1f}% "
                f"{res['profit_factor']:<8.3f} {res['avg_net_pp']:<+9.3f} "
                f"{res['avg_win_pp']:<+9.2f} {res['avg_loss_pp']:<+9.2f}"
            )


if __name__ == "__main__":
    main()
