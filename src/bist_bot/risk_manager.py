from bist_bot.config.settings import settings
from bist_bot.risk.manager import RiskManager
from bist_bot.risk.models import RiskLevels

__all__ = ["RiskLevels", "RiskManager"]


if __name__ == "__main__":
    from bist_bot.data.fetcher import BISTDataFetcher
    from bist_bot.indicators import TechnicalIndicators

    fetcher = BISTDataFetcher()
    ti = TechnicalIndicators()
    rm = RiskManager(capital=getattr(settings, "INITIAL_CAPITAL", 8500.0))

    test_tickers = ["ASELS.IS", "THYAO.IS", "BIMAS.IS"]

    for ticker in test_tickers:
        print(f"\n{'='*50}")
        print(f"📊 {ticker}")
        print(f"{'='*50}")

        df = fetcher.fetch_single(ticker, period="6mo")
        if df is not None:
            df = ti.add_all(df)
            levels = rm.calculate(df)

            price = df["close"].iloc[-1]
            print(f"\n  Fiyat: ₺{price:.2f}")
            print(f"  Stop-Loss: ₺{levels.final_stop:.2f} ({levels.risk_pct:+.1f}%)")
            print(f"  Hedef: ₺{levels.final_target:.2f} ({levels.reward_pct:+.1f}%)")
            print(f"  R/R: 1:{levels.risk_reward_ratio:.1f}")
            print(f"  Lot: {levels.position_size}")
            print(f"  Max Kayıp: ₺{levels.max_loss_tl:.2f}")
            print(f"  Yöntem: {levels.method_used}")
