"""End-to-end example: plugging a custom strategy into the BIST Bot engine.

Run from project root:
    python examples/plug_in_strategy.py

This file demonstrates how a developer can:
1. Implement their own ``BaseStrategy`` subclass with a custom signal rule.
2. Register it via ``engine.register_strategy()``.
3. Call ``engine.scan_with_plugins()`` to get merged signals from both the
   built-in engine and all registered plugins.
4. Load risk parameters from an external YAML file using ``RiskProfileLoader``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without installing the package (editable install recommended).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

from bist_bot.risk.profile import RiskProfile, RiskProfileLoader
from bist_bot.strategy.base import BaseStrategy
from bist_bot.strategy.engine import StrategyEngine
from bist_bot.strategy.signal_models import Signal, SignalType


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Implement a custom strategy
# ─────────────────────────────────────────────────────────────────────────────

class GoldenCrossStrategy(BaseStrategy):
    """Simple 50/200 MA Golden-Cross strategy.

    Generates a BUY signal when the 50-day MA crosses above the 200-day MA
    on the most recent candle.  Returns None (no signal) otherwise.

    This serves as a minimal reference implementation of ``BaseStrategy``.
    """

    @property
    def name(self) -> str:
        return "GoldenCrossStrategy"

    def analyze(
        self, ticker: str, data: pd.DataFrame | dict[str, pd.DataFrame]
    ) -> Signal | None:
        # Handle multi-timeframe dict – use the trigger frame
        df = data.get("trigger") if isinstance(data, dict) else data
        if df is None or len(df) < 200:
            return None

        ma50 = df["close"].rolling(50).mean()
        ma200 = df["close"].rolling(200).mean()

        # Golden cross: previous candle below, latest candle above
        if ma50.iloc[-2] < ma200.iloc[-2] and ma50.iloc[-1] >= ma200.iloc[-1]:
            last_close = float(df["close"].iloc[-1])
            return Signal(
                ticker=ticker,
                signal_type=SignalType.STRONG_BUY,
                score=85.0,
                price=last_close,
                reasons=["50MA crossed above 200MA (golden cross)"],
                stop_loss=round(last_close * 0.97, 2),
                target_price=round(last_close * 1.06, 2),
                confidence="confidence.high",
            )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Load risk profile from external YAML
# ─────────────────────────────────────────────────────────────────────────────

loader = RiskProfileLoader()
profile: RiskProfile = loader.load()

print("\n✅  Risk profile loaded:")
print(f"   Max risk / trade : {profile.max_risk_pct}%")
print(f"   Max position cap : {profile.max_position_cap_pct}%")
print(f"   Daily loss limit : {profile.max_daily_loss_pct}%")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Build the engine and register the custom strategy
# ─────────────────────────────────────────────────────────────────────────────

engine = StrategyEngine()
golden_cross = GoldenCrossStrategy()
engine.register_strategy(golden_cross)

print(f"\n🔧  Registered strategies: {[s.name for s in engine._strategies]}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Create synthetic data and run scan_with_plugins
# ─────────────────────────────────────────────────────────────────────────────

def _make_golden_cross_df(n: int = 210) -> pd.DataFrame:
    """Create a dataframe where a golden cross occurs on the last candle."""
    import numpy as np
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    close = pd.Series(100.0, index=range(n))
    # Simulate a gradual uptrend that causes MA cross near the end
    close[:150] = 95.0
    close[150:] = 106.0
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 0.3, n)
    close = (close + noise).clip(lower=1.0)
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close.values,
            "volume": rng.integers(100_000, 500_000, n),
        },
        index=dates,
    )


sample_data: dict[str, pd.DataFrame] = {
    "THYAO.IS": _make_golden_cross_df(),
}

print("\n🚀  Running scan_with_plugins …")
signals = engine.scan_with_plugins(sample_data)

if signals:
    print(f"\n📊  {len(signals)} signal(s) found:")
    for sig in signals:
        print(f"   [{sig.signal_type.name}] {sig.ticker}  score={sig.score:+.1f}")
else:
    print("\n⚠️  No signals generated (try adjusting synthetic data or thresholds).")

print("\nDone.")
