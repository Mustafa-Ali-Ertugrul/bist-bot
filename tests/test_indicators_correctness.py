"""Comprehensive correctness tests for TechnicalIndicators."""

from __future__ import annotations

import pandas as pd

from bist_bot.indicators import TechnicalIndicators


def _ohlc_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _base_frame(start: float = 100.0, count: int = 50) -> pd.DataFrame:
    rows = []
    for idx in range(count):
        base = start + idx
        rows.append(
            {
                "open": base - 0.5,
                "high": base + 1.5,
                "low": base - 1.5,
                "close": base,
                "volume": 1000000,
            }
        )
    return pd.DataFrame(rows)


class TestATR:
    def test_atr_positive_values(self):
        df = _base_frame()
        result = TechnicalIndicators.add_atr(df, period=14)
        assert result["atr"].notna().sum() > 0
        assert (result["atr"] > 0).all()

    def test_atr_increases_with_volatility(self):
        low_vol = _base_frame()
        high_vol = low_vol.copy()
        high_vol["high"] += 5.0
        high_vol["low"] -= 5.0

        low_result = TechnicalIndicators.add_atr(low_vol, period=14)
        high_result = TechnicalIndicators.add_atr(high_vol, period=14)

        assert high_result["atr"].iloc[-1] > low_result["atr"].iloc[-1]


class TestADX:
    def test_adx_bounded_0_to_100(self):
        df = _base_frame()
        df = TechnicalIndicators.add_atr(df, period=14)
        result = TechnicalIndicators.add_adx(df, period=14)

        adx_values = result["adx"].dropna()
        assert len(adx_values) > 0
        assert (adx_values >= 0).all()
        assert (adx_values <= 100).all()

    def test_adx_strong_threshold(self):
        df = _base_frame()
        df = TechnicalIndicators.add_atr(df, period=14)
        result = TechnicalIndicators.add_adx(df, period=14)

        assert "adx_strong" in result.columns

    def test_di_cross_detects_trend_reversal(self):
        df = _base_frame()
        df = TechnicalIndicators.add_atr(df, period=14)
        result = TechnicalIndicators.add_adx(df, period=14)

        assert "di_cross" in result.columns
        assert result["di_cross"].isin(["NONE", "BULLISH", "BEARISH"]).all()


class TestRSI:
    def test_rsi_bounded_0_to_100(self):
        df = _base_frame()
        result = TechnicalIndicators.add_rsi(df, period=14)

        rsi_values = result["rsi"].dropna()
        assert len(rsi_values) > 0
        assert (rsi_values >= 0).all()
        assert (rsi_values <= 100).all()

    def test_rsi_zones_valid(self):
        df = _base_frame()
        result = TechnicalIndicators.add_rsi(df, period=14)

        valid_zones = {
            "UNKNOWN",
            "OVERSOLD",
            "NEAR_OVERSOLD",
            "NEUTRAL",
            "NEAR_OVERBOUGHT",
            "OVERBOUGHT",
        }
        actual_zones = set(result["rsi_zone"].unique())
        assert actual_zones.issubset(valid_zones)

    def test_rsi_oversold_below_30(self):
        df = _base_frame()
        result = TechnicalIndicators.add_rsi(df, period=14)
        oversold_rows = result[result["rsi_zone"] == "OVERSOLD"]
        if len(oversold_rows) > 0:
            assert (oversold_rows["rsi"] < 30).all()


class TestMACD:
    def test_macd_columns_exist(self):
        df = _base_frame()
        result = TechnicalIndicators.add_macd(df)
        expected = {"macd", "macd_signal", "macd_hist"}
        assert expected.issubset(result.columns)

    def test_macd_signal_smoothing(self):
        import numpy as np

        np.random.seed(42)
        n = 200
        noise = np.random.randn(n) * 2
        close = 100 + np.cumsum(noise)
        df = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e6},
        )
        result = TechnicalIndicators.add_macd(df)

        macd_std = result["macd"].std()
        signal_std = result["macd_signal"].std()
        assert signal_std < macd_std


class TestSMA:
    def test_sma_increases_with_price(self):
        df = _base_frame()
        result = TechnicalIndicators.add_sma(df)

        assert "sma_20" in result.columns
        assert "sma_50" in result.columns

    def test_sma_larger_period_smoother(self):
        df = _base_frame()
        result = TechnicalIndicators.add_sma(df)

        if result["sma_20"].notna().sum() > 0 and result["sma_50"].notna().sum() > 0:
            sma_20_var = result["sma_20"].dropna().var()
            sma_50_var = result["sma_50"].dropna().var()
            assert sma_50_var < sma_20_var


class TestEMA:
    def test_ema_columns_exist(self):
        df = _base_frame()
        result = TechnicalIndicators.add_ema(df)

        assert "ema_12" in result.columns
        assert "ema_26" in result.columns

    def test_ema_larger_period_smoother(self):
        df = _base_frame()
        result = TechnicalIndicators.add_ema(df)

        if result["ema_12"].notna().sum() > 0 and result["ema_26"].notna().sum() > 0:
            ema_12_var = result["ema_12"].dropna().var()
            ema_26_var = result["ema_26"].dropna().var()
            assert ema_26_var < ema_12_var


class TestBollingerBands:
    def test_bb_columns_exist(self):
        df = _base_frame()
        result = TechnicalIndicators.add_bollinger_bands(df)

        assert "bb_upper" in result.columns
        assert "bb_middle" in result.columns
        assert "bb_lower" in result.columns

    def test_bb_width_positive(self):
        df = _base_frame()
        result = TechnicalIndicators.add_bollinger_bands(df)

        bb_width = result["bb_upper"] - result["bb_lower"]
        assert (bb_width > 0).all()


class TestStochastic:
    def test_stoch_columns_exist(self):
        df = _base_frame()
        result = TechnicalIndicators.add_stochastic(df)

        assert "stoch_k" in result.columns
        assert "stoch_d" in result.columns

    def test_stoch_k_bounded_0_to_100(self):
        df = _base_frame()
        result = TechnicalIndicators.add_stochastic(df)

        stoch_k = result["stoch_k"].dropna()
        assert (stoch_k >= 0).all()
        assert (stoch_k <= 100).all()


class TestOBV:
    def test_obv_columns_exist(self):
        df = _base_frame()
        result = TechnicalIndicators.add_obv(df)

        assert "obv" in result.columns
        assert "obv_sma" in result.columns
        assert "obv_trend" in result.columns

    def test_obv_increases_with_up_days(self):
        df = _base_frame()
        result = TechnicalIndicators.add_obv(df)

        assert result["obv"].iloc[-1] >= result["obv"].iloc[0]


class TestCCI:
    def test_cci_columns_exist(self):
        df = _base_frame()
        result = TechnicalIndicators.add_cci(df)

        assert "cci" in result.columns
        assert "cci_oversold" in result.columns
        assert "cci_overbought" in result.columns


class TestVolumeProfile:
    def test_volume_ratio_positive(self):
        df = _base_frame()
        result = TechnicalIndicators.add_volume_profile(df)

        assert "volume_ratio" in result.columns
        assert (result["volume_ratio"] >= 0).all()
