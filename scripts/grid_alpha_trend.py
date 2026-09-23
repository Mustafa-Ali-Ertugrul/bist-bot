"""Grid Search & Stress Test for BIST Alpha Trend Strategy."""

from __future__ import annotations

from scripts.prototype_alpha_trend import run_alpha_backtest


def run_grid():
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

    print(
        f"{'Trail Mult':<12} {'Max Stop':<10} {'Trades':<8} {'Win Rate':<10} {'PF':<8} {'Avg Net':<10} {'Avg Win':<10} {'Avg Loss':<10}"
    )
    print("-" * 80)

    for trail in [2.0, 2.5, 3.0]:
        for max_stop in [4.0, 5.0, 6.0]:
            res = run_alpha_backtest(bist30, period="2y", trail_mult=trail, max_stop_pct=max_stop)
            print(
                f"{trail:<12.1f} {max_stop:<10.1f} {res['n']:<8} {res['win_rate']:<9.1f}% {res['profit_factor']:<8.3f} {res['avg_net_pp']:<+9.3f} {res['avg_win_pp']:<+9.2f} {res['avg_loss_pp']:<+9.2f}"
            )


if __name__ == "__main__":
    run_grid()
