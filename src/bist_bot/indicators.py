import numpy as np
import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings

logger = get_logger(__name__, component="indicators")


class TechnicalIndicators:
    @staticmethod
    def _nanargmin(values: np.ndarray) -> float:
        if np.isnan(values).all():
            return np.nan
        return float(np.nanargmin(values))

    @staticmethod
    def _add_min_divergence(
        df: pd.DataFrame,
        source_col: str,
        output_col: str,
        lookback: int,
        low_threshold: float,
        high_threshold: float,
    ) -> pd.DataFrame:
        df = df.copy()
        df[output_col] = "NONE"

        if len(df) < lookback * 2:
            return df

        source = df[source_col]
        price = df["close"]
        n_rows = len(df)
        row_positions = np.arange(n_rows)

        current_min = source.rolling(window=lookback + 1, min_periods=lookback + 1).min()
        current_argmin = source.rolling(window=lookback + 1, min_periods=lookback + 1).apply(
            TechnicalIndicators._nanargmin,
            raw=True,
        )

        previous_source = source.shift(lookback + 1)
        previous_min = previous_source.rolling(window=lookback, min_periods=1).min()
        previous_argmin = previous_source.rolling(window=lookback, min_periods=1).apply(
            TechnicalIndicators._nanargmin,
            raw=True,
        )

        current_positions = row_positions - lookback + current_argmin.to_numpy(dtype=float)
        previous_starts = np.maximum(0, row_positions - (lookback * 2))
        previous_positions = previous_starts + previous_argmin.to_numpy(dtype=float)

        price_values = price.to_numpy(dtype=float)
        current_price = np.full(n_rows, np.nan, dtype=float)
        previous_price = np.full(n_rows, np.nan, dtype=float)

        valid_current_pos = ~np.isnan(current_positions)
        valid_previous_pos = ~np.isnan(previous_positions)

        current_pos_int = current_positions[valid_current_pos].astype(int)
        previous_pos_int = previous_positions[valid_previous_pos].astype(int)
        current_price[valid_current_pos] = price_values[current_pos_int]
        previous_price[valid_previous_pos] = price_values[previous_pos_int]

        bullish = (
            (current_min < low_threshold)
            & (current_min > previous_min)
            & (current_price < previous_price)
        )
        bearish = (
            (current_min > high_threshold)
            & (current_min < previous_min)
            & (current_price > previous_price)
        )

        eligible_rows = (row_positions >= lookback) & (row_positions < n_rows - 1)
        bullish &= eligible_rows
        bearish &= eligible_rows

        df.loc[bullish, output_col] = "BULLISH"
        df.loc[bearish, output_col] = "BEARISH"
        return df

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
    def add_rsi(df: pd.DataFrame, period: int | None = None) -> pd.DataFrame:
        period = period or settings.RSI_PERIOD
        df = df.copy()

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)

        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))
        df["rsi"] = df["rsi"].replace([np.inf, -np.inf], np.nan).clip(0, 100)

        df["rsi_zone"] = "UNKNOWN"
        rsi = df["rsi"]
        df.loc[rsi.between(0, 30, inclusive="both"), "rsi_zone"] = "OVERSOLD"
        df.loc[rsi.gt(30) & rsi.le(45), "rsi_zone"] = "NEAR_OVERSOLD"
        df.loc[rsi.gt(45) & rsi.le(55), "rsi_zone"] = "NEUTRAL"
        df.loc[rsi.gt(55) & rsi.le(70), "rsi_zone"] = "NEAR_OVERBOUGHT"
        df.loc[rsi.gt(70) & rsi.le(100), "rsi_zone"] = "OVERBOUGHT"
        df["rsi_zone"] = df["rsi_zone"].astype(object)
        return df

    @staticmethod
    def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        df = df.copy()

        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()

        df["stoch_k"] = 100 * (df["close"] - low_min) / (high_max - low_min)
        df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()

        df["stoch_cross"] = "NONE"
        bullish = (df["stoch_k"] > df["stoch_d"]) & (
            df["stoch_k"].shift(1) <= df["stoch_d"].shift(1)
        )
        bearish = (df["stoch_k"] < df["stoch_d"]) & (
            df["stoch_k"].shift(1) >= df["stoch_d"].shift(1)
        )
        df.loc[bullish, "stoch_cross"] = "BULLISH"
        df.loc[bearish, "stoch_cross"] = "BEARISH"

        df["stoch_oversold"] = (df["stoch_k"] < 20) & (df["stoch_d"] < 20)
        df["stoch_overbought"] = (df["stoch_k"] > 80) & (df["stoch_d"] > 80)

        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        df = df.copy()
        if "atr" not in df.columns:
            df = TechnicalIndicators.add_atr(df, period=period)

        high_diff = df["high"].diff()
        low_diff = -df["low"].diff()

        df["plus_dm"] = pd.Series(
            np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0),
            index=df.index,
        )
        df["minus_dm"] = pd.Series(
            np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0),
            index=df.index,
        )

        smoothed_plus_dm = (
            df["plus_dm"].ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        )
        smoothed_minus_dm = (
            df["minus_dm"].ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        )
        atr = df["atr"].replace(0, np.nan)

        plus_di = 100 * smoothed_plus_dm / atr
        minus_di = 100 * smoothed_minus_dm / atr

        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / di_sum
        df["adx"] = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().clip(0, 100)
        df["plus_di"] = plus_di.clip(0, 100)
        df["minus_di"] = minus_di.clip(0, 100)

        df["adx_strong"] = df["adx"] > 25
        df["di_cross"] = "NONE"
        bullish_di = (df["plus_di"] > df["minus_di"]) & (
            df["plus_di"].shift(1) <= df["minus_di"].shift(1)
        )
        bearish_di = (df["plus_di"] < df["minus_di"]) & (
            df["plus_di"].shift(1) >= df["minus_di"].shift(1)
        )
        df.loc[bullish_di, "di_cross"] = "BULLISH"
        df.loc[bearish_di, "di_cross"] = "BEARISH"

        df = df.drop(columns=["plus_dm", "minus_dm"], errors="ignore")
        return df

    @staticmethod
    def add_obv(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"].to_numpy()
        volume = df["volume"].to_numpy()
        direction = np.sign(np.diff(close, prepend=close[0]))
        signed_volume = direction * volume
        signed_volume[0] = 0
        df["obv"] = np.cumsum(signed_volume)
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
        return TechnicalIndicators._add_min_divergence(
            df=df,
            source_col="rsi",
            output_col="rsi_divergence",
            lookback=lookback,
            low_threshold=35,
            high_threshold=65,
        )

    @staticmethod
    def add_macd_divergence(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
        return TechnicalIndicators._add_min_divergence(
            df=df,
            source_col="macd",
            output_col="macd_divergence",
            lookback=lookback,
            low_threshold=0,
            high_threshold=0,
        )

    @staticmethod
    def add_sma(df: pd.DataFrame, fast: int | None = None, slow: int | None = None) -> pd.DataFrame:
        fast = fast or settings.SMA_FAST
        slow = slow or settings.SMA_SLOW
        df = df.copy()

        df[f"sma_{fast}"] = df["close"].rolling(window=fast, min_periods=1).mean()
        df[f"sma_{slow}"] = df["close"].rolling(window=slow, min_periods=1).mean()
        if "sma_20" not in df.columns:
            df["sma_20"] = df["close"].rolling(window=20, min_periods=1).mean()
        if "sma_50" not in df.columns:
            df["sma_50"] = df["close"].rolling(window=50, min_periods=1).mean()

        fast_col = f"sma_{fast}"
        slow_col = f"sma_{slow}"

        df["sma_cross"] = "NONE"
        golden = (df[fast_col] > df[slow_col]) & (df[fast_col].shift(1) <= df[slow_col].shift(1))
        death = (df[fast_col] < df[slow_col]) & (df[fast_col].shift(1) >= df[slow_col].shift(1))
        df.loc[golden, "sma_cross"] = "GOLDEN_CROSS"
        df.loc[death, "sma_cross"] = "DEATH_CROSS"
        return df

    @staticmethod
    def add_ema(df: pd.DataFrame, fast: int | None = None, slow: int | None = None) -> pd.DataFrame:
        fast = fast or settings.EMA_FAST
        slow = slow or settings.EMA_SLOW
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

        fast = settings.MACD_FAST
        slow = settings.MACD_SLOW
        signal_period = settings.MACD_SIGNAL
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal_period, adjust=False, min_periods=1).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        df["macd_hist"] = df["macd_histogram"]

        df["macd_cross"] = "NONE"
        bullish = (df["macd"] > df["macd_signal"]) & (
            df["macd"].shift(1) <= df["macd_signal"].shift(1)
        )
        bearish = (df["macd"] < df["macd_signal"]) & (
            df["macd"].shift(1) >= df["macd_signal"].shift(1)
        )
        df.loc[bullish, "macd_cross"] = "BULLISH"
        df.loc[bearish, "macd_cross"] = "BEARISH"

        df["macd_hist_increasing"] = df["macd_histogram"].diff() > 0

        return df

    @staticmethod
    def add_bollinger(
        df: pd.DataFrame, period: int | None = None, std: float | None = None
    ) -> pd.DataFrame:
        period = period or settings.BOLLINGER_PERIOD
        std = std or settings.BOLLINGER_STD
        df = df.copy()

        df["bb_middle"] = df["close"].rolling(window=period, min_periods=1).mean()
        rolling_std = (
            df["close"].rolling(window=period, min_periods=1).std().fillna(0.0).clip(lower=1e-9)
        )
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
    def add_bollinger_bands(
        df: pd.DataFrame, period: int | None = None, std: float | None = None
    ) -> pd.DataFrame:
        return TechnicalIndicators.add_bollinger(df, period=period, std=std)

    @staticmethod
    def add_volume_analysis(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["volume_sma_20"] = df["volume"].rolling(window=20, min_periods=1).mean()
        df["volume_ratio"] = (df["volume"] / df["volume_sma_20"]).fillna(0.0)
        df["volume_spike"] = df["volume_ratio"] >= settings.VOLUME_SPIKE_MULTIPLIER

        price_up = df["close"] > df["close"].shift(1)
        vol_up = df["volume"] > df["volume"].shift(1)
        df["price_volume_direction"] = "NONE"
        df.loc[price_up & vol_up, "price_volume_direction"] = "BULLISH_CONFIRMATION"
        df.loc[~price_up & vol_up, "price_volume_direction"] = "BEARISH_CONFIRMATION"
        df.loc[~price_up & ~vol_up, "price_volume_direction"] = "LOW_VOLUME_PULLBACK"
        df["price_volume_confirm"] = df["price_volume_direction"] == "BULLISH_CONFIRMATION"

        df["volume_trend"] = "FLAT"
        df.loc[df["volume_sma_20"].diff() > 0, "volume_trend"] = "INCREASING"
        df.loc[df["volume_sma_20"].diff() < 0, "volume_trend"] = "DECREASING"

        return df

    @staticmethod
    def add_volume_profile(df: pd.DataFrame) -> pd.DataFrame:
        return TechnicalIndicators.add_volume_analysis(df)

    @staticmethod
    def volume_confirmed(
        df: pd.DataFrame,
        ticker: str | None = None,
        threshold: float | None = None,
    ) -> bool:
        if df is None or len(df) < 25:
            return False

        last = df.iloc[-1]
        vol_ratio = float(last.get("volume_ratio", 1.0) or 0.0)

        if ticker:
            base_threshold = getattr(settings, "VOLUME_CONFIRM_MULTIPLIER", 1.5)
            overrides = getattr(settings, "VOLUME_CONFIRM_TICKER_OVERRIDES", {})
            threshold = threshold or overrides.get(ticker, base_threshold)
        else:
            threshold = threshold or 1.5

        return bool(vol_ratio >= threshold)

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        df = df.copy()

        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift(1))
        low_close = abs(df["low"] - df["close"].shift(1))

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
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

        cross_values = {
            "sma_cross": str(last.get("sma_cross", "NONE")),
            "macd_cross": str(last.get("macd_cross", "NONE")),
            "bb_position": str(last.get("bb_position", "MIDDLE")),
        }
        for key, val in cross_values.items():
            if val and isinstance(val, str):
                val = val.replace("<", "↓").replace(">", "↑")
                cross_values[key] = val

        return {
            "close": round(last.get("close", 0), 2),
            "change_pct": round((last["close"] - prev["close"]) / prev["close"] * 100, 2)
            if "close" in last.index
            else 0,
            "volume": int(last.get("volume", 0)),
            "rsi": round(last.get("rsi", 50), 2),
            "rsi_zone": str(last.get("rsi_zone", "NÖTR")),
            "sma_cross": cross_values["sma_cross"],
            "ema_cross": str(last.get("ema_cross", "NONE")),
            "macd_cross": cross_values["macd_cross"],
            "stoch_cross": str(last.get("stoch_cross", "NONE")),
            "stoch_k": round(last.get("stoch_k", 50), 1),
            "stoch_d": round(last.get("stoch_d", 50), 1),
            "adx": round(last.get("adx", 0), 1),
            "cci": round(last.get("cci", 0), 1),
            "bb_position": cross_values["bb_position"],
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
