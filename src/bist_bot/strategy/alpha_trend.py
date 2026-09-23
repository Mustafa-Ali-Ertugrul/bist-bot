"""BIST Alpha Trend Strategy (Institutional Momentum & Relative Strength).

Designed for Borsa Istanbul (BIST30 / BIST100).
Replaces lagged retail indicators with institutional edge:
1. Macro Hard-Gate: XU100 > SMA50 & SMA20 (no longs in market correction/bear).
2. Relative Strength (RS): Stock outperforming XU100 across 20-day and 50-day horizons.
3. Volume Surge: Institutional accumulation volume (>= 1.4x 20-day volume SMA).
4. High Breakout: Closing above previous 20-day high with candle in top 35% of daily range.
5. Asymmetric Payoff: Tight initial stop (1.5 ATR / max 4-5%), trailing stop 2.5-3.0 ATR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_bot.strategy.base import BaseStrategy
from bist_bot.strategy.signal_models import Signal, SignalType


class AlphaTrendStrategy(BaseStrategy):
    """Institutional Relative Strength & Momentum strategy for BIST."""

    def __init__(
        self,
        xu100_df: pd.DataFrame | None = None,
        trail_mult: float = 3.0,
        max_stop_pct: float = 4.5,
        volume_surge_mult: float = 1.4,
        breakout_bars: int = 20,
    ) -> None:
        # Constructor'a geçirilen ham benchmark verisi de set_benchmark
        # hattından geçsin: sma50/sma20/is_bullish hesaplanmadan bırakılırsa
        # makro kapı fail-open çalışır (ayı rejiminde sinyal kaçırırdı).
        if xu100_df is not None:
            self.set_benchmark(xu100_df)
        else:
            self.xu100_df = None
        self.trail_mult = float(trail_mult)
        self.max_stop_pct = float(max_stop_pct)
        self.volume_surge_mult = float(volume_surge_mult)
        self.breakout_bars = int(breakout_bars)

    @property
    def name(self) -> str:
        return "AlphaTrendStrategy"

    def set_benchmark(self, xu100_df: pd.DataFrame) -> None:
        """Update the benchmark index DataFrame for Relative Strength calculation."""
        df = xu100_df.copy()
        df.columns = [c.lower() for c in df.columns]
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma20"] = df["close"].rolling(20).mean()
        df["is_bullish"] = (df["close"] > df["sma50"]) & (df["close"] > df["sma20"])
        self.xu100_df = df

    def analyze(self, ticker: str, data: pd.DataFrame | dict[str, pd.DataFrame]) -> Signal | None:
        """Analyze a stock for Relative Strength & Volume breakout setup."""
        if isinstance(data, dict):
            df = data.get("trend") or data.get("trigger")
        else:
            df = data

        if df is None or len(df) < max(60, self.breakout_bars + 20):
            return None

        stock = df.copy()
        stock.columns = [c.lower() for c in stock.columns]

        # 1. Macro Regime Check (if benchmark available)
        if self.xu100_df is not None:
            common_idx = stock.index.intersection(self.xu100_df.index)
            if len(common_idx) < 50:
                return None
            bench_last = self.xu100_df.loc[common_idx].iloc[-1]
            # Fail-closed: is_bullish sütunu yoksa (set_benchmark atlanmışsa)
            # varsayılan True ile kapı açık kalmasın — sinyal üretilmesin.
            if not bool(bench_last.get("is_bullish", False)):
                # Macro market is in correction / bear -> Hard-Gate Cash Protection
                return None

            bench_close = self.xu100_df.loc[common_idx, "close"]
            rs = stock.loc[common_idx, "close"] / bench_close
            rs_sma20 = rs.rolling(20).mean()
            rs_sma50 = rs.rolling(50).mean()

            # RS Condition: Stock must outperform index
            if not (rs.iloc[-1] > rs_sma20.iloc[-1] and rs_sma20.iloc[-1] > rs_sma50.iloc[-1]):
                return None
            rs_outperformance = round(float((rs.iloc[-1] / rs_sma20.iloc[-1] - 1.0) * 100.0), 2)
        else:
            rs_outperformance = 0.0

        # 2. Volume Expansion
        vol_sma20 = stock["volume"].rolling(20).mean()
        last_vol = float(stock["volume"].iloc[-1])
        avg_vol = float(vol_sma20.iloc[-1])
        if avg_vol <= 0 or last_vol < (self.volume_surge_mult * avg_vol):
            return None
        vol_surge_ratio = round(last_vol / avg_vol, 2)

        # 3. 20-Day High Breakout
        high_20 = stock["high"].iloc[-self.breakout_bars - 1 : -1].max()
        last_close = float(stock["close"].iloc[-1])
        last_open = float(stock["open"].iloc[-1])
        last_high = float(stock["high"].iloc[-1])
        last_low = float(stock["low"].iloc[-1])

        if last_close < high_20:
            return None

        # 4. Strong Candle Formation (Green candle, close in upper 35% of range)
        candle_range = last_high - last_low
        if candle_range <= 0:
            return None
        close_pos = (last_close - last_low) / candle_range
        if last_close <= last_open or close_pos < 0.65:
            return None

        # 5. Volatility & Risk Sizing (ATR)
        tr = np.maximum(
            stock["high"] - stock["low"],
            np.maximum(
                (stock["high"] - stock["close"].shift(1)).abs(),
                (stock["low"] - stock["close"].shift(1)).abs(),
            ),
        )
        atr = float(tr.rolling(14).mean().iloc[-1])
        if atr <= 0:
            return None

        init_stop_raw = last_close - (1.5 * atr)
        max_allowed_stop = last_close * (1.0 - self.max_stop_pct / 100.0)
        stop_price = round(max(init_stop_raw, max_allowed_stop), 2)

        # Min 1.5% stop cushion
        if (last_close - stop_price) / last_close < 0.015:
            stop_price = round(last_close * 0.985, 2)

        risk_pct = round((last_close - stop_price) / last_close * 100.0, 2)

        # Trailing Target (Reference target 3x risk for UI / reporting, position managed by trail)
        target_price = round(last_close + (3.0 * (last_close - stop_price)), 2)

        reasons = [
            f"Endeks Üstü Göreceli Güç: XU100'e karşı +%{rs_outperformance}",
            f"Kurumsal Hacim Patlaması: 20G ortalamanın {vol_surge_ratio}x katı",
            f"{self.breakout_bars} Günlük Zirve Kırılımı (Direnç aşıldı)",
            f"Güçlü Gün İçi Kapanış (Mum boyunun %{int(close_pos * 100)} zirvesinde)",
            f"Sıkı Risk Kontrolü: %{risk_pct} stop (Açık kâr sürme hedefli)",
        ]

        score = min(33.0, round(25.0 + (vol_surge_ratio * 2.0) + (rs_outperformance * 0.5), 1))

        return Signal(
            ticker=ticker,
            signal_type=SignalType.STRONG_BUY if score >= 28.0 else SignalType.BUY,
            score=score,
            price=last_close,
            reasons=reasons,
            stop_loss=stop_price,
            target_price=target_price,
            confidence="confidence.high",
            is_actionable=True,
            buy_threshold=20.0,
            score_breakdown={
                "relative_strength": round(rs_outperformance, 2),
                "volume_surge": round(vol_surge_ratio, 2),
                "breakout": 10.0,
            },
        )
