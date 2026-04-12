import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from sklearn.ensemble import GradientBoostingRegressor
from typing import Optional, List
import logging
import os
import pickle
import threading

import config
from indicators import TechnicalIndicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_model_lock = threading.Lock()

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df

class PricePredictor:
    def __init__(
        self, 
        sequence_length: Optional[int] = None,
        model_path: Optional[str] = None
    ):
        self.feature_version = 2
        self.sequence_length = sequence_length or getattr(config, "ML_SEQUENCE_LENGTH", 60)
        self.model_path = model_path or getattr(config, "ML_MODEL_PATH", "models")
        self.scaler = MinMaxScaler()
        self.model = None
        self.models = {}
        self.is_trained = False
        self._min_data_points = self.sequence_length + 50
        
        if not os.path.exists(self.model_path):
            os.makedirs(self.model_path)

    def _normalize_input_data(self, data: pd.DataFrame) -> pd.DataFrame:
        df = _flatten_columns(data.copy())
        df.columns = [str(col).lower() for col in df.columns]
        return df

    def _get_close_values(self, data: pd.DataFrame) -> np.ndarray:
        if isinstance(data, pd.DataFrame):
            if 'close' not in data.columns:
                raise KeyError("Input data must include 'close' column")
            close = data['close'].to_numpy().flatten()
        else:
            close = data.to_numpy().flatten()
        return close.astype(float)

    def _validate_data(self, data: pd.DataFrame) -> bool:
        if data is None or data.empty:
            return False
            
        if len(data) < self._min_data_points:
            return False
            
        return True

    def _create_features(self, data: pd.DataFrame, scaled_close: np.ndarray) -> np.ndarray:
        df = TechnicalIndicators.add_all(data.copy())

        scaled_series = pd.Series(scaled_close, index=df.index)
        close = df["close"]
        volume = df["volume"] if "volume" in df.columns else pd.Series(0.0, index=df.index)
        obv = df["obv"] if "obv" in df.columns else pd.Series(0.0, index=df.index)
        returns_1 = close.pct_change()

        feature_frame = pd.DataFrame(index=df.index)

        feature_frame["close_scaled"] = scaled_series
        feature_frame["close_mean_5"] = scaled_series.shift(1).rolling(5).mean()
        feature_frame["close_mean_20"] = scaled_series.shift(1).rolling(20).mean()
        feature_frame["close_mean_60"] = scaled_series.shift(1).rolling(60).mean()
        feature_frame["close_std_10"] = scaled_series.shift(1).rolling(10).std()

        feature_frame["close_lag_1"] = scaled_series.shift(1)
        feature_frame["close_lag_2"] = scaled_series.shift(2)
        feature_frame["close_lag_3"] = scaled_series.shift(3)
        feature_frame["close_lag_5"] = scaled_series.shift(5)

        feature_frame["return_1"] = returns_1
        feature_frame["return_3"] = close.pct_change(3)
        feature_frame["return_5"] = close.pct_change(5)
        feature_frame["return_10"] = close.pct_change(10)
        feature_frame["momentum_5"] = close / close.shift(5) - 1.0
        feature_frame["momentum_10"] = close / close.shift(10) - 1.0

        feature_frame["return_vol_5"] = returns_1.rolling(5).std()
        feature_frame["return_vol_10"] = returns_1.rolling(10).std()
        feature_frame["return_vol_20"] = returns_1.rolling(20).std()
        feature_frame["price_range_10"] = (close.rolling(10).max() - close.rolling(10).min()) / close
        feature_frame["price_range_20"] = (close.rolling(20).max() - close.rolling(20).min()) / close

        ema_fast = df.get(f"ema_{config.EMA_FAST}")
        ema_slow = df.get(f"ema_{config.EMA_SLOW}")
        feature_frame["rsi"] = df.get("rsi")
        feature_frame["macd"] = df.get("macd")
        feature_frame["macd_signal"] = df.get("macd_signal")
        feature_frame["macd_histogram"] = df.get("macd_histogram")
        feature_frame["ema_fast_ratio"] = (ema_fast / close) - 1.0 if ema_fast is not None else 0.0
        feature_frame["ema_slow_ratio"] = (ema_slow / close) - 1.0 if ema_slow is not None else 0.0
        feature_frame["ema_spread"] = (ema_fast / ema_slow) - 1.0 if ema_fast is not None and ema_slow is not None else 0.0
        feature_frame["stoch_k"] = df.get("stoch_k")
        feature_frame["stoch_d"] = df.get("stoch_d")

        feature_frame["bb_percent"] = df.get("bb_percent")
        feature_frame["bb_bandwidth"] = df.get("bb_bandwidth")
        feature_frame["atr_pct"] = df.get("atr") / close
        feature_frame["adx"] = df.get("adx")
        feature_frame["plus_di"] = df.get("plus_di")
        feature_frame["minus_di"] = df.get("minus_di")

        feature_frame["volume_ratio"] = df.get("volume_ratio")
        feature_frame["volume_change_1"] = volume.pct_change()
        feature_frame["volume_change_5"] = volume.pct_change(5)
        feature_frame["volume_vol_10"] = volume.pct_change().rolling(10).std()
        feature_frame["obv_change_1"] = obv.diff()
        feature_frame["obv_change_5"] = obv.diff(5)

        feature_frame["bias"] = 1.0

        feature_frame = feature_frame.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return feature_frame.to_numpy(dtype=float)

    def _build_training_set(
        self,
        features: np.ndarray,
        close: np.ndarray,
        horizon: int
    ) -> tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        max_start = len(features) - horizon + 1

        for i in range(self.sequence_length, max_start):
            X.append(features[i - self.sequence_length:i].flatten())
            y.append(close[i + horizon - 1])

        return np.array(X), np.array(y)

    def train(
        self,
        data: pd.DataFrame,
        epochs: Optional[int] = None,
        batch_size: Optional[int] = None,
        validation_split: float = 0.2,
        max_horizon: int = 1
    ) -> bool:
        data = self._normalize_input_data(data)
        
        if not self._validate_data(data):
            return False
            
        try:
            close = self._get_close_values(data)

            split_idx = int(len(close) * (1 - validation_split))
            split_idx = max(split_idx, self.sequence_length + 1)
            split_idx = min(split_idx, len(close) - 1)

            train_close = close[:split_idx].reshape(-1, 1)
            full_close = close.reshape(-1, 1)

            self.scaler.fit(train_close)
            scaled_close = self.scaler.transform(full_close).flatten()
            features = self._create_features(data, scaled_close)
            self.models = {}

            max_horizon = max(1, int(max_horizon))

            for horizon in range(1, max_horizon + 1):
                X, y = self._build_training_set(features, close, horizon)

                if len(X) < 10:
                    return False

                train_samples = max(split_idx - self.sequence_length - horizon + 1, 1)
                train_samples = min(train_samples, len(X) - 1)

                X_train, X_val = X[:train_samples], X[train_samples:]
                y_train, y_val = y[:train_samples], y[train_samples:]

                if len(X_val) == 0:
                    return False

                model = GradientBoostingRegressor(
                    n_estimators=100,
                    max_depth=5,
                    learning_rate=0.1,
                    random_state=42
                )
                model.fit(X_train, y_train)
                self.models[horizon] = model

            self.model = self.models.get(1)
            
            self.is_trained = True
            return True
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False

    def predict(self, last_n_features: np.ndarray, horizon: int = 1) -> Optional[float]:
        model = self.models.get(horizon) or (self.model if horizon == 1 else None)

        if not self.is_trained or model is None:
            return None
            
        try:
            X = last_n_features.flatten().reshape(1, -1)
            return float(model.predict(X)[0])
        except:
            return None

    def save_model(self, ticker: str) -> bool:
        if not self.models and self.model is None:
            return False
            
        try:
            path = f"{self.model_path}/{ticker}_model.pkl"
            with open(path, "wb") as f:
                pickle.dump({
                    "feature_version": self.feature_version,
                    "models": self.models,
                    "model": self.model,
                    "scaler": self.scaler,
                    "sequence_length": self.sequence_length
                }, f)
            return True
        except Exception as e:
            logger.error(f"Save failed: {e}")
            return False

    def load_model(self, ticker: str) -> bool:
        path = f"{self.model_path}/{ticker}_model.pkl"
        if not os.path.exists(path):
            return False
            
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            if data.get("feature_version") != self.feature_version:
                return False
            self.models = data.get("models", {})
            self.model = data.get("model")
            if not self.models and self.model is not None:
                self.models = {1: self.model}
            elif self.model is None and 1 in self.models:
                self.model = self.models[1]
            self.scaler = data["scaler"]
            self.sequence_length = data["sequence_length"]
            self.is_trained = True
            return True
        except Exception as e:
            logger.error(f"Load failed: {e}")
            return False


def predict_price(ticker: str, data: pd.DataFrame, days_ahead: int = 1) -> Optional[List[float]]:
    if data is None or len(data) < 60:
        return None
    
    predictor = PricePredictor()
    data = predictor._normalize_input_data(data)
    days_ahead = max(1, int(days_ahead))
    
    with _model_lock:
        loaded = predictor.load_model(ticker)
        has_required_horizons = loaded and all(h in predictor.models for h in range(1, days_ahead + 1))

        if not has_required_horizons:
            if not predictor.train(data, max_horizon=days_ahead):
                return None
            predictor.save_model(ticker)
        
        close = predictor._get_close_values(data).reshape(-1, 1)
        scaled_close = predictor.scaler.transform(close).flatten()
        features = predictor._create_features(data, scaled_close)
        last_n = features[-predictor.sequence_length:]
        predictions = []

        for horizon in range(1, days_ahead + 1):
            pred = predictor.predict(last_n, horizon=horizon)
            if pred is None:
                break
            predictions.append(pred)
    
    return predictions if predictions else None


def get_signal_from_prediction(current_price: float, predicted_price: float) -> str:
    change_pct = (predicted_price - current_price) / current_price * 100
    
    if change_pct > 3:
        return "STRONG_BUY"
    elif change_pct > 1:
        return "BUY"
    elif change_pct < -3:
        return "STRONG_SELL"
    elif change_pct < -1:
        return "SELL"
    else:
        return "HOLD"
