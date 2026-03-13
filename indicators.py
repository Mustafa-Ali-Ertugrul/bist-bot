import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Optional
import logging

import config

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    @staticmethod
    def add_all(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df = TechnicalIndicators.add_rsi(df)
        df = TechnicalIndicators.add_sma(df)
        df = TechnicalIndicators.add_ema(df)
        df = TechnicalIndicators.add_macd(df)
        df = TechnicalIndicators.add_bollinger(df)
        df = TechnicalIndicators.add_volume_analysis(df)
        df = TechnicalIndicators.add_atr(df)
        df = TechnicalIndicators.add_stochastic(df)
        df = TechnicalIndicators.add_support_resistance(df)

        return df

    @staticmethod
    def add_rsi(
        df: pd.DataFrame,
        period: int = None
    ) -> pd.DataFrame:
        period = period or config.RSI_PERIOD
        df = df.copy()

        df["rsi"] = ta.rsi(df["close"], length=period)

        df["rsi_zone"] = pd.cut(
            df["rsi"],
            bins=[0, 30, 45, 55, 70, 100],
            labels=[
                "AŞIRI_SATIM",
                "SATIN_YAKINI",
                "NÖTR",
                "ALIMIN_YAKINI",
                "AŞIRI_ALIM"
            ]
        )

        return df

    @staticmethod
    def add_sma(
        df: pd.DataFrame,
        fast: int = None,
        slow: int = None
    ) -> pd.DataFrame:
        fast = fast or config.SMA_FAST
        slow = slow or config.SMA_SLOW
        df = df.copy()

        df[f"sma_{fast}"] = df["close"].rolling(window=fast).mean()
        df[f"sma_{slow}"] = df["close"].rolling(window=slow).mean()

        fast_col = f"sma_{fast}"
        slow_col = f"sma_{slow}"

        df["sma_cross"] = "NONE"

        golden = (
            (df[fast_col] > df[slow_col]) &
            (df[fast_col].shift(1) <= df[slow_col].shift(1))
        )
        death = (
            (df[fast_col] < df[slow_col]) &
            (df[fast_col].shift(1) >= df[slow_col].shift(1))
        )

        df.loc[golden, "sma_cross"] = "GOLDEN_CROSS"
        df.loc[death, "sma_cross"] = "DEATH_CROSS"

        return df

    @staticmethod
    def add_ema(
        df: pd.DataFrame,
        fast: int = None,
        slow: int = None
    ) -> pd.DataFrame:
        fast = fast or config.EMA_FAST
        slow = slow or config.EMA_SLOW
        df = df.copy()

        df[f"ema_{fast}"] = ta.ema(df["close"], length=fast)
        df[f"ema_{slow}"] = ta.ema(df["close"], length=slow)

        return df

    @staticmethod
    def add_macd(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        macd_result = ta.macd(
            df["close"],
            fast=config.MACD_FAST,
            slow=config.MACD_SLOW,
            signal=config.MACD_SIGNAL
        )

        if macd_result is not None:
            df["macd"] = macd_result.iloc[:, 0]
            df["macd_histogram"] = macd_result.iloc[:, 1]
            df["macd_signal"] = macd_result.iloc[:, 2]

            df["macd_cross"] = "NONE"
            bullish = (
                (df["macd"] > df["macd_signal"]) &
                (df["macd"].shift(1) <= df["macd_signal"].shift(1))
            )
            bearish = (
                (df["macd"] < df["macd_signal"]) &
                (df["macd"].shift(1) >= df["macd_signal"].shift(1))
            )
            df.loc[bullish, "macd_cross"] = "BULLISH"
            df.loc[bearish, "macd_cross"] = "BEARISH"

        return df

    @staticmethod
    def add_bollinger(
        df: pd.DataFrame,
        period: int = None,
        std: float = None
    ) -> pd.DataFrame:
        period = period or config.BOLLINGER_PERIOD
        std = std or config.BOLLINGER_STD
        df = df.copy()

        bb = ta.bbands(df["close"], length=period, std=std)

        if bb is not None:
            df["bb_lower"] = bb.iloc[:, 0]
            df["bb_middle"] = bb.iloc[:, 1]
            df["bb_upper"] = bb.iloc[:, 2]
            df["bb_bandwidth"] = bb.iloc[:, 3]
            df["bb_percent"] = bb.iloc[:, 4]

            df["bb_position"] = "MIDDLE"
            df.loc[df["close"] <= df["bb_lower"], "bb_position"] = "BELOW_LOWER"
            df.loc[df["close"] >= df["bb_upper"], "bb_position"] = "ABOVE_UPPER"

        return df

    @staticmethod
    def add_volume_analysis(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["volume_sma_20"] = df["volume"].rolling(window=20).mean()

        df["volume_ratio"] = df["volume"] / df["volume_sma_20"]

        df["volume_spike"] = (
            df["volume_ratio"] >= config.VOLUME_SPIKE_MULTIPLIER
        )

        price_up = df["close"] > df["close"].shift(1)
        vol_up = df["volume"] > df["volume"].shift(1)

        df["price_volume_confirm"] = (
            (price_up & vol_up) | (~price_up & ~vol_up)
        )

        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        df = df.copy()
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=period)

        df["stop_loss_atr"] = df["close"] - (2 * df["atr"])

        return df

    @staticmethod
    def add_stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3
    ) -> pd.DataFrame:
        df = df.copy()

        stoch = ta.stoch(
            df["high"], df["low"], df["close"],
            k=k_period, d=d_period
        )

        if stoch is not None:
            df["stoch_k"] = stoch.iloc[:, 0]
            df["stoch_d"] = stoch.iloc[:, 1]

        return df

    @staticmethod
    def add_support_resistance(
        df: pd.DataFrame,
        lookback: int = 20
    ) -> pd.DataFrame:
        df = df.copy()

        df["support"] = df["low"].rolling(window=lookback).min()
        df["resistance"] = df["high"].rolling(window=lookback).max()

        df["dist_to_support_pct"] = (
            (df["close"] - df["support"]) / df["close"] * 100
        )
        df["dist_to_resistance_pct"] = (
            (df["resistance"] - df["close"]) / df["close"] * 100
        )

        return df

    @staticmethod
    def get_snapshot(df: pd.DataFrame) -> dict:
        if df.empty:
            return {}

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        snapshot = {
            "close": round(last.get("close", 0), 2),
            "change_pct": round(
                (last["close"] - prev["close"]) / prev["close"] * 100, 2
            ) if "close" in last.index else 0,
            "volume": int(last.get("volume", 0)),
            "rsi": round(last.get("rsi", 50), 2),
            "rsi_zone": str(last.get("rsi_zone", "NÖTR")),
            "sma_cross": str(last.get("sma_cross", "NONE")),
            "macd_cross": str(last.get("macd_cross", "NONE")),
            "bb_position": str(last.get("bb_position", "MIDDLE")),
            "volume_spike": bool(last.get("volume_spike", False)),
            "volume_ratio": round(last.get("volume_ratio", 1), 2),
            "atr": round(last.get("atr", 0), 2),
            "stop_loss": round(last.get("stop_loss_atr", 0), 2),
            "support": round(last.get("support", 0), 2),
            "resistance": round(last.get("resistance", 0), 2),
        }

        return snapshot


if __name__ == "__main__":
    from data_fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    df = fetcher.fetch_single("ASELS.IS", period="6mo")

    if df is not None:
        ti = TechnicalIndicators()
        df = ti.add_all(df)

        print("\n📊 ASELSAN — Son 5 Gün (Tüm İndikatörler):")
        print(df[["close", "rsi", "sma_5", "sma_20", "macd", "bb_lower",
                   "bb_upper", "atr", "volume_ratio"]].tail())

        print("\n📋 Anlık Özet:")
        snapshot = ti.get_snapshot(df)
        for key, val in snapshot.items():
            print(f"  {key:>20}: {val}")
