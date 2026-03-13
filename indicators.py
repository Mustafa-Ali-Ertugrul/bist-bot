import pandas as pd
import numpy as np
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
        df = TechnicalIndicators.add_support_resistance(df)
        return df

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
        period = period or config.RSI_PERIOD
        df = df.copy()
        
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))
        
        df["rsi_zone"] = pd.cut(
            df["rsi"],
            bins=[0, 30, 45, 55, 70, 100],
            labels=["AŞIRI_SATIM", "SATIN_YAKINI", "NÖTR", "ALIMIN_YAKINI", "AŞIRI_ALIM"]
        )
        return df

    @staticmethod
    def add_sma(df: pd.DataFrame, fast: int = None, slow: int = None) -> pd.DataFrame:
        fast = fast or config.SMA_FAST
        slow = slow or config.SMA_SLOW
        df = df.copy()
        
        df[f"sma_{fast}"] = df["close"].rolling(window=fast).mean()
        df[f"sma_{slow}"] = df["close"].rolling(window=slow).mean()
        
        fast_col = f"sma_{fast}"
        slow_col = f"sma_{slow}"
        
        df["sma_cross"] = "NONE"
        golden = (df[fast_col] > df[slow_col]) & (df[fast_col].shift(1) <= df[slow_col].shift(1))
        death = (df[fast_col] < df[slow_col]) & (df[fast_col].shift(1) >= df[slow_col].shift(1))
        df.loc[golden, "sma_cross"] = "GOLDEN_CROSS"
        df.loc[death, "sma_cross"] = "DEATH_CROSS"
        return df

    @staticmethod
    def add_ema(df: pd.DataFrame, fast: int = None, slow: int = None) -> pd.DataFrame:
        fast = fast or config.EMA_FAST
        slow = slow or config.EMA_SLOW
        df = df.copy()
        
        df[f"ema_{fast}"] = df["close"].ewm(span=fast, adjust=False).mean()
        df[f"ema_{slow}"] = df["close"].ewm(span=slow, adjust=False).mean()
        return df

    @staticmethod
    def add_macd(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        
        df["macd_cross"] = "NONE"
        bullish = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))
        bearish = (df["macd"] < df["macd_signal"]) & (df["macd"].shift(1) >= df["macd_signal"].shift(1))
        df.loc[bullish, "macd_cross"] = "BULLISH"
        df.loc[bearish, "macd_cross"] = "BEARISH"
        return df

    @staticmethod
    def add_bollinger(df: pd.DataFrame, period: int = None, std: float = None) -> pd.DataFrame:
        period = period or config.BOLLINGER_PERIOD
        std = std or config.BOLLINGER_STD
        df = df.copy()
        
        df["bb_middle"] = df["close"].rolling(window=period).mean()
        rolling_std = df["close"].rolling(window=period).std()
        df["bb_upper"] = df["bb_middle"] + (rolling_std * std)
        df["bb_lower"] = df["bb_middle"] - (rolling_std * std)
        df["bb_bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"] * 100
        df["bb_percent"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
        
        df["bb_position"] = "MIDDLE"
        df.loc[df["close"] <= df["bb_lower"], "bb_position"] = "BELOW_LOWER"
        df.loc[df["close"] >= df["bb_upper"], "bb_position"] = "ABOVE_UPPER"
        return df

    @staticmethod
    def add_volume_analysis(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        df["volume_sma_20"] = df["volume"].rolling(window=20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma_20"]
        df["volume_spike"] = df["volume_ratio"] >= config.VOLUME_SPIKE_MULTIPLIER
        
        price_up = df["close"] > df["close"].shift(1)
        vol_up = df["volume"] > df["volume"].shift(1)
        df["price_volume_confirm"] = (price_up & vol_up) | (~price_up & ~vol_up)
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        df = df.copy()
        
        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift(1))
        low_close = abs(df["low"] - df["close"].shift(1))
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=period).mean()
        df["stop_loss_atr"] = df["close"] - (2 * df["atr"])
        return df

    @staticmethod
    def add_support_resistance(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
        df = df.copy()
        
        df["support"] = df["low"].rolling(window=lookback).min()
        df["resistance"] = df["high"].rolling(window=lookback).max()
        df["dist_to_support_pct"] = (df["close"] - df["support"]) / df["close"] * 100
        df["dist_to_resistance_pct"] = (df["resistance"] - df["close"]) / df["close"] * 100
        return df

    @staticmethod
    def get_snapshot(df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        
        return {
            "close": round(last.get("close", 0), 2),
            "change_pct": round((last["close"] - prev["close"]) / prev["close"] * 100, 2) if "close" in last.index else 0,
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
