import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from typing import Optional, List
import logging
import os
import pickle
import threading

import config

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
        model_path: str = None
    ):
        self.sequence_length = sequence_length or getattr(config, "ML_SEQUENCE_LENGTH", 60)
        self.model_path = model_path or getattr(config, "ML_MODEL_PATH", "models")
        self.scaler = MinMaxScaler()
        self.model = None
        self.is_trained = False
        self._min_data_points = self.sequence_length + 50
        
        if not os.path.exists(self.model_path):
            os.makedirs(self.model_path)

    def _validate_data(self, data: pd.DataFrame) -> bool:
        if data is None or data.empty:
            return False
            
        if len(data) < self._min_data_points:
            return False
            
        return True

    def _create_features(self, data: pd.DataFrame) -> np.ndarray:
        if isinstance(data, pd.DataFrame):
            close = data['Close'].values.flatten()
        else:
            close = data.values.flatten()
        
        close_arr = close.reshape(-1, 1)
        scaled = self.scaler.fit_transform(close_arr).flatten()
        
        n = len(close)
        features = np.zeros((n, 6))
        
        for i in range(n):
            features[i, 0] = scaled[i]
            if i >= 4:
                features[i, 1] = np.mean(scaled[max(0, i-5):i])
            if i >= 19:
                features[i, 2] = np.mean(scaled[max(0, i-20):i])
            if i >= 59:
                features[i, 3] = np.mean(scaled[max(0, i-60):i])
            if i >= 9:
                features[i, 4] = np.std(scaled[max(0, i-10):i])
            features[i, 5] = 1.0
        
        return features

    def train(self, data: pd.DataFrame, epochs: int = None, batch_size: int = None, validation_split: float = 0.2) -> bool:
        data = _flatten_columns(data)
        
        if not self._validate_data(data):
            return False
            
        try:
            features = self._create_features(data)
            close = data['Close'].values.flatten()
            
            X, y = [], []
            for i in range(self.sequence_length, len(features)):
                X.append(features[i - self.sequence_length:i].flatten())
                y.append(close[i])
            X, y = np.array(X), np.array(y)
            
            if len(X) < 10:
                return False
            
            X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=validation_split, shuffle=False)
            
            self.model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
            self.model.fit(X_train, y_train)
            
            self.is_trained = True
            return True
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False

    def predict(self, last_n_features: np.ndarray) -> Optional[float]:
        if not self.is_trained or self.model is None:
            return None
            
        try:
            X = last_n_features.flatten().reshape(1, -1)
            return float(self.model.predict(X)[0])
        except:
            return None

    def save_model(self, ticker: str) -> bool:
        if self.model is None:
            return False
            
        try:
            path = f"{self.model_path}/{ticker}_model.pkl"
            with open(path, "wb") as f:
                pickle.dump({
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
            self.model = data["model"]
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
    
    with _model_lock:
        if not predictor.load_model(ticker):
            if not predictor.train(data):
                return None
            predictor.save_model(ticker)
        
        features = predictor._create_features(data)
        last_n = features[-predictor.sequence_length:]
        predictions = []
        
        temp_features = last_n.copy()
        
        for _ in range(days_ahead):
            pred = predictor.predict(temp_features)
            if pred is None:
                break
            predictions.append(pred)
            
            temp_features = np.roll(temp_features, -1, axis=0)
            temp_features[-1, 0] = pred
            temp_features[-1, 1] = np.mean(temp_features[-5:, 0])
    
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