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
        df = TechnicalIndicators.add_adx(df)
        df = TechnicalIndicators.add_support_resistance(df)
        df = TechnicalIndicators.add_stochastic(df)
        df = TechnicalIndicators.add_obv(df)
        df = TechnicalIndicators.add_cci(df)
        df = TechnicalIndicators.add_rsi_divergence(df)
        df = TechnicalIndicators.add_macd_divergence(df)
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
    def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        df = df.copy()
        
        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()
        
        df["stoch_k"] = 100 * (df["close"] - low_min) / (high_max - low_min)
        df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
        
        df["stoch_cross"] = "NONE"
        bullish = (df["stoch_k"] > df["stoch_d"]) & (df["stoch_k"].shift(1) <= df["stoch_d"].shift(1))
        bearish = (df["stoch_k"] < df["stoch_d"]) & (df["stoch_k"].shift(1) >= df["stoch_d"].shift(1))
        df.loc[bullish, "stoch_cross"] = "BULLISH"
        df.loc[bearish, "stoch_cross"] = "BEARISH"
        
        df["stoch_oversold"] = (df["stoch_k"] < 20) & (df["stoch_d"] < 20)
        df["stoch_overbought"] = (df["stoch_k"] > 80) & (df["stoch_d"] > 80)
        
        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        df = df.copy()
        
        high_diff = df["high"].diff()
        low_diff = -df["low"].diff()
        
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
        
        df["plus_dm"] = plus_dm
        df["minus_dm"] = low_diff.clip(lower=0)
        df.loc[low_diff <= high_diff, "minus_dm"] = 0
        
        plus_di = 100 * pd.Series(plus_dm).rolling(window=period).mean() / df["atr"]
        minus_di = 100 * pd.Series(minus_dm).rolling(window=period).mean() / df["atr"]
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df["adx"] = dx.rolling(window=period).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        
        df["adx_strong"] = df["adx"] > 25
        df["di_cross"] = "NONE"
        bullish_di = (df["plus_di"] > df["minus_di"]) & (df["plus_di"].shift(1) <= df["minus_di"].shift(1))
        bearish_di = (df["plus_di"] < df["minus_di"]) & (df["plus_di"].shift(1) >= df["minus_di"].shift(1))
        df.loc[bullish_di, "di_cross"] = "BULLISH"
        df.loc[bearish_di, "di_cross"] = "BEARISH"
        
        df = df.drop(columns=["plus_dm", "minus_dm"], errors="ignore")
        return df

    @staticmethod
    def add_obv(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        obv = np.zeros(len(df))
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i - 1]:
                obv[i] = obv[i - 1] + df["volume"].iloc[i]
            elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
                obv[i] = obv[i - 1] - df["volume"].iloc[i]
            else:
                obv[i] = obv[i - 1]
        
        df["obv"] = obv
        df["obv_sma"] = df["obv"].rolling(window=20).mean()
        df["obv_trend"] = "FLAT"
        df.loc[df["obv"] > df["obv_sma"], "obv_trend"] = "UP"
        df.loc[df["obv"] < df["obv_sma"], "obv_trend"] = "DOWN"
        
        return df

    @staticmethod
    def add_cci(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        df = df.copy()
        
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp = typical_price.rolling(window=period).mean()
        mean_dev = typical_price.rolling(window=period).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        
        df["cci"] = (typical_price - sma_tp) / (0.015 * mean_dev)
        
        df["cci_oversold"] = df["cci"] < -100
        df["cci_overbought"] = df["cci"] > 100
        
        return df

    @staticmethod
    def add_rsi_divergence(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
        df = df.copy()
        
        df["rsi_divergence"] = "NONE"
        
        if len(df) < lookback * 2:
            return df
        
        for i in range(lookback, len(df) - 1):
            rsi_window = df["rsi"].iloc[i - lookback:i + 1]
            price_window = df["close"].iloc[i - lookback:i + 1]
            
            if rsi_window.isna().any() or price_window.isna().any():
                continue
            
            rsi_min_idx = rsi_window.idxmin()
            rsi_min = rsi_window.min()
            price_at_rsi_min = df["close"].loc[rsi_min_idx]
            
            prev_slice = df["rsi"].iloc[max(0, i - lookback * 2):i - lookback]
            if prev_slice.dropna().empty:
                continue
            prev_rsi_min_idx = prev_slice.idxmin()
            if pd.isna(prev_rsi_min_idx):
                continue
            
            prev_rsi_min = df["rsi"].loc[prev_rsi_min_idx]
            prev_price_at_rsi_min = df["close"].loc[prev_rsi_min_idx]
            
            if rsi_min < 35 and rsi_min > prev_rsi_min and price_at_rsi_min < prev_price_at_rsi_min:
                df.loc[df.index[i], "rsi_divergence"] = "BULLISH"
            elif rsi_min > 65 and rsi_min < prev_rsi_min and price_at_rsi_min > prev_price_at_rsi_min:
                df.loc[df.index[i], "rsi_divergence"] = "BEARISH"
        
        return df

    @staticmethod
    def add_macd_divergence(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
        df = df.copy()
        
        df["macd_divergence"] = "NONE"
        
        if len(df) < lookback * 2:
            return df
        
        for i in range(lookback, len(df) - 1):
            macd_window = df["macd"].iloc[i - lookback:i + 1]
            price_window = df["close"].iloc[i - lookback:i + 1]
            
            if macd_window.isna().any() or price_window.isna().any():
                continue
            
            macd_min_idx = macd_window.idxmin()
            macd_min = macd_window.min()
            price_at_macd_min = df["close"].loc[macd_min_idx]
            
            prev_slice = df["macd"].iloc[max(0, i - lookback * 2):i - lookback]
            if prev_slice.dropna().empty:
                continue
            prev_macd_min_idx = prev_slice.idxmin()
            if pd.isna(prev_macd_min_idx):
                continue
            
            prev_macd_min = df["macd"].loc[prev_macd_min_idx]
            prev_price_at_macd_min = df["close"].loc[prev_macd_min_idx]
            
            if macd_min < 0 and macd_min > prev_macd_min and price_at_macd_min < prev_price_at_macd_min:
                df.loc[df.index[i], "macd_divergence"] = "BULLISH"
            elif macd_min > 0 and macd_min < prev_macd_min and price_at_macd_min > prev_price_at_macd_min:
                df.loc[df.index[i], "macd_divergence"] = "BEARISH"
        
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
        
        fast_col = f"ema_{fast}"
        slow_col = f"ema_{slow}"
        
        df["ema_cross"] = "NONE"
        bullish = (df[fast_col] > df[slow_col]) & (df[fast_col].shift(1) <= df[slow_col].shift(1))
        bearish = (df[fast_col] < df[slow_col]) & (df[fast_col].shift(1) >= df[slow_col].shift(1))
        df.loc[bullish, "ema_cross"] = "BULLISH"
        df.loc[bearish, "ema_cross"] = "BEARISH"
        
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
        
        df["macd_hist_increasing"] = df["macd_histogram"].diff() > 0
        
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
        
        df["bb_squeeze"] = df["bb_bandwidth"] < df["bb_bandwidth"].rolling(window=20).mean() * 0.7
        
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
        
        df["volume_trend"] = "FLAT"
        df.loc[df["volume_sma_20"].diff() > 0, "volume_trend"] = "INCREASING"
        df.loc[df["volume_sma_20"].diff() < 0, "volume_trend"] = "DECREASING"
        
        return df
    
    @staticmethod
    def volume_confirmed(df: pd.DataFrame, threshold: float = None) -> bool:
        threshold = threshold or getattr(config, "VOLUME_CONFIRM_MULTIPLIER", 1.5)
        last = df.iloc[-1]
        vol_ratio = last.get("volume_ratio", 1.0)
        return vol_ratio >= threshold

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
            "ema_cross": str(last.get("ema_cross", "NONE")),
            "macd_cross": str(last.get("macd_cross", "NONE")),
            "stoch_cross": str(last.get("stoch_cross", "NONE")),
            "stoch_k": round(last.get("stoch_k", 50), 1),
            "stoch_d": round(last.get("stoch_d", 50), 1),
            "adx": round(last.get("adx", 0), 1),
            "cci": round(last.get("cci", 0), 1),
            "bb_position": str(last.get("bb_position", "MIDDLE")),
            "volume_spike": bool(last.get("volume_spike", False)),
            "volume_ratio": round(last.get("volume_ratio", 1), 2),
            "atr": round(last.get("atr", 0), 2),
            "stop_loss": round(last.get("stop_loss_atr", 0), 2),
            "support": round(last.get("support", 0), 2),
            "resistance": round(last.get("resistance", 0), 2),
            "rsi_divergence": str(last.get("rsi_divergence", "NONE")),
            "macd_divergence": str(last.get("macd_divergence", "NONE")),
            "obv_trend": str(last.get("obv_trend", "FLAT")),
        }
