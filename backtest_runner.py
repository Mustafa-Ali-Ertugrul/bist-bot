import logging
from pathlib import Path

import config

from backtest import Backtester


logger = logging.getLogger(__name__)


def run_backtest(fetcher):
    logger.info("\n🧪 BACKTEST BAŞLIYOR")
    logger.info("=" * 55)

    backtester = Backtester(initial_capital=getattr(config.settings, "INITIAL_CAPITAL", 8500.0))
    output_dir = Path("data")
    results = []

    for ticker in config.settings.WATCHLIST:
        df = fetcher.fetch_single(ticker, period="1y")
        if df is not None:
            output_path = output_dir / f"backtest_{ticker.replace('.', '_')}.json"
            result = backtester.run(ticker, df, verbose=False, output_path=output_path)
            if result:
                results.append(result)
                print(result)

    if results:
        avg_return = sum(r.total_return_pct for r in results) / len(results)
        avg_winrate = sum(r.win_rate for r in results) / len(results)
        total_trades = sum(r.total_trades for r in results)

        print(f"\n{'═'*55}")
        print("📊 GENEL BACKTEST ÖZETİ")
        print(f"{'═'*55}")
        print(f"  Test edilen : {len(results)} hisse")
        print(f"  Toplam işlem: {total_trades}")
        print(f"  Ort. getiri : %{avg_return:.2f}")
        print(f"  Ort. win rate: %{avg_winrate:.1f}")

        best = max(results, key=lambda r: r.total_return_pct)
        worst = min(results, key=lambda r: r.total_return_pct)
        print(f"  En iyi      : {best.ticker} (%{best.total_return_pct:+.2f})")
        print(f"  En kötü     : {worst.ticker} (%{worst.total_return_pct:+.2f})")
        print(f"{'═'*55}")
