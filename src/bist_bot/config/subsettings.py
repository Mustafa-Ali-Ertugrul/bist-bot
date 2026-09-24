"""Composable sub-settings groups for the main Settings facade."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from bist_bot.data.bist100 import BIST100_TICKERS

# D3: hatali env degerleri sessizce default'a dusmek yerine kayda gecer;
# CONFIG_STRICT=true iken settings preflight bunlari FATAL yapar.
MALFORMED_ENV_VALUES: list[tuple[str, str, str]] = []  # (name, raw_value, expected_type)


def get_malformed_env_values() -> list[tuple[str, str, str]]:
    return list(MALFORMED_ENV_VALUES)


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    MALFORMED_ENV_VALUES.append((name, value, "bool"))
    return default


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        MALFORMED_ENV_VALUES.append((name, value, "int"))
        return default


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        MALFORMED_ENV_VALUES.append((name, value, "float"))
        return default


def _get_str_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        file_path = os.getenv(f"{name}_FILE")
        if not file_path:
            return default
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return default
    return value.strip()


def _get_table_name_env(name: str, default: str = "paper_trades") -> str:
    value = _get_str_env(name, default)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
        raise ValueError(f"Invalid SQL table name configured for {name}: {value!r}")
    return value


def _get_csv_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return ()
    items = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(items)


DEFAULT_FLASK_PORT = _get_int_env("PORT", _get_int_env("FLASK_PORT", 5000))

DEFAULT_BIST100_WATCHLIST = BIST100_TICKERS

TICKER_NAMES = {
    "THYAO.IS": "THY",
    "ASELS.IS": "ASELSAN",
    "SASA.IS": "SASA",
    "KCHOL.IS": "Koç Holding",
    "EREGL.IS": "Ereğli",
    "BIMAS.IS": "BİM",
    "TUPRS.IS": "Tüpraş",
    "SAHOL.IS": "Sabancı Holding",
    "GARAN.IS": "Garanti BBVA",
    "TAVHL.IS": "TAV Havalimanları",
    "TOASO.IS": "Tofaş",
    "FROTO.IS": "Ford Otosan",
    "PETKM.IS": "Petkim",
    "KRDMD.IS": "Kardemir",
    "HEKTS.IS": "Hektaş",
    "AYGAZ.IS": "Aygaz",
    "ISCTR.IS": "İş Bankası",
    "YKBNK.IS": "Yapı Kredi",
    "HALKB.IS": "Halkbank",
    "VAKBN.IS": "VakıfBank",
    "AKSA.IS": "Aksa",
    "ARCLK.IS": "Arçelik",
    "CCOLA.IS": "Coca-Cola İçecek",
    "CIMSA.IS": "Çimsa",
    "CLEBI.IS": "Clebi",
    "ENJSA.IS": "Enerjisa Enerji",
    "ERBOS.IS": "Erbos",
    "FENIS.IS": "Feniş",
    "FMIZP.IS": "Federal-Mogul Izmit Piston",
    "FORMT.IS": "Formet",
    "GENTS.IS": "Gentas",
    "GLYHO.IS": "Gülho",
    "IPEKE.IS": "İpek",
    "IZMDC.IS": "İzdemir",
    "KARSN.IS": "Karsan",
    "KAYSE.IS": "Kayseri Seker",
    "KONTR.IS": "Kontrol",
    "KORFM.IS": "Korfm",
    "LKMNH.IS": "Lokman",
    "MAKIM.IS": "Makim",
    "MGROS.IS": "Migros",
    "AEFES.IS": "Anadolu Efes",
    "TTKOM.IS": "Türk Telekom",
    "TRALT.IS": "Türk Altın",
    "DSTKF.IS": "Destek Faktoring",
    "GUBRF.IS": "Gübretaş",
    "ENKAI.IS": "ENKA",
    "EKGYO.IS": "Emlak GYO",
    "ASTOR.IS": "Astor Enerji",
    "AKBNK.IS": "Akbank",
    "PGSUS.IS": "Pegasus",
    "MRGYO.IS": "Merit Gayrimenkul",
    "ODAS.IS": "Odas",
    "PNLSN.IS": "Pınar",
    "PSDTC.IS": "Pasifik Donanim",
    "SEKFK.IS": "Şeker",
    "SEKFS.IS": "Şeker Finans",
    "SOKM.IS": "ŞOK Marketler",
}

SECTOR_MAP = {
    "THYAO.IS": "HAVACILIK",
    "PGSUS.IS": "HAVACILIK",
    "TAVHL.IS": "HAVACILIK",
    "ASELS.IS": "SAVUNMA",
    "SASA.IS": "KİMYA",
    "PETKM.IS": "KİMYA",
    "KCHOL.IS": "HOLDİNG",
    "SAHOL.IS": "HOLDİNG",
    "EREGL.IS": "DEMİR-ÇELİK",
    "KRDMD.IS": "DEMİR-ÇELİK",
    "BIMAS.IS": "PERAKENDE",
    "MGROS.IS": "PERAKENDE",
    "SOKM.IS": "PERAKENDE",
    "TUPRS.IS": "ENERJİ",
    "AYGAZ.IS": "ENERJİ",
    "ENJSA.IS": "ENERJİ",
    "ODAS.IS": "ENERJİ",
    "GWIND.IS": "ENERJİ",
    "GARAN.IS": "BANKA",
    "AKBNK.IS": "BANKA",
    "ISCTR.IS": "BANKA",
    "YKBNK.IS": "BANKA",
    "HALKB.IS": "BANKA",
    "VAKBN.IS": "BANKA",
    "TOASO.IS": "OTOMOTİV",
    "FROTO.IS": "OTOMOTİV",
    "DOAS.IS": "OTOMOTİV",
    "ARCLK.IS": "DAYANIKLI",
    "VESBE.IS": "DAYANIKLI",
    "CCOLA.IS": "GIDA",
    "AEFES.IS": "GIDA",
    "ULKER.IS": "GIDA",
    "SISE.IS": "CAM",
    "HEKTS.IS": "TARIM",
    "CIMSA.IS": "ÇİMENTO",
    "AKCNS.IS": "ÇİMENTO",
    "OYAKC.IS": "ÇİMENTO",
    "ENKAI.IS": "İNŞAAT",
    "TKFEN.IS": "İNŞAAT",
    "TCELL.IS": "TELEKOM",
    "TTKOM.IS": "TELEKOM",
    "ISGYO.IS": "GYO",
    "EKGYO.IS": "GYO",
    "TRALT.IS": "MADENCİLİK",
    "DSTKF.IS": "FİNANS",
    "GUBRF.IS": "KİMYA",
    "ASTOR.IS": "ENERJİ",
}


@dataclass(frozen=True)
class TradingSettings:
    STRONG_BUY_THRESHOLD: int = _get_int_env("STRONG_BUY_THRESHOLD", 48)
    WEAK_BUY_THRESHOLD: int = _get_int_env("WEAK_BUY_THRESHOLD", 8)
    WEAK_SELL_THRESHOLD: int = _get_int_env("WEAK_SELL_THRESHOLD", -8)
    SELL_THRESHOLD: int = _get_int_env("SELL_THRESHOLD", -20)
    STRONG_SELL_THRESHOLD: int = _get_int_env("STRONG_SELL_THRESHOLD", -48)
    SIDEWAYS_EXTRA_THRESHOLD: float = _get_float_env("SIDEWAYS_EXTRA_THRESHOLD", 5.0)
    MOMENTUM_CONFIRMATION_THRESHOLD: float = _get_float_env("MOMENTUM_CONFIRMATION_THRESHOLD", 4.0)
    MACRO_REGIME_GATE_ENABLED: bool = _get_bool_env("MACRO_REGIME_GATE_ENABLED", True)
    # USD/TRY döviz-riski cezası + XU100 doğrudan voter (varsayılan kapalı;
    # açıldığında davranış değişir — backtest ablation ile doğrulanmalı).
    FOREX_FILTER_ENABLED: bool = _get_bool_env("FOREX_FILTER_ENABLED", False)
    FOREX_PENALTY_POINTS: float = _get_float_env("FOREX_PENALTY_POINTS", 5.0)
    FOREX_RISK_SECTORS: tuple[str, ...] = field(
        default_factory=lambda: _get_csv_env("FOREX_RISK_SECTORS") or ("HAVACILIK",)
    )
    FOREX_TREND_LOOKBACK: int = _get_int_env("FOREX_TREND_LOOKBACK", 20)
    USDTRY_TICKER: str = _get_str_env("USDTRY_TICKER", "USDTRY=X")
    XU100_VOTER_ENABLED: bool = _get_bool_env("XU100_VOTER_ENABLED", False)
    XU100_TICKER: str = _get_str_env("XU100_TICKER", "XU100.IS")
    # Gun-ici seans metrikleri (2026-09-17 gozlemi: tepki gunleri, taban
    # kilitleri, sektor liderligi). Varsayilan ACIK — kucuk cap'li (±8)
    # additif ayar; esik kalibrasyonu korunur.
    SESSION_ADJ_ENABLED: bool = _get_bool_env("SESSION_ADJ_ENABLED", True)
    SESSION_LIMIT_DOWN_BLOCK: bool = _get_bool_env("SESSION_LIMIT_DOWN_BLOCK", True)
    SESSION_LIMIT_UP_PENALTY: float = _get_float_env("SESSION_LIMIT_UP_PENALTY", 6.0)
    SESSION_RANGE_POS_MIN: float = _get_float_env("SESSION_RANGE_POS_MIN", 0.8)
    SESSION_RECOVERY_MIN_PCT: float = _get_float_env("SESSION_RECOVERY_MIN_PCT", 2.0)
    SESSION_RECOVERY_BONUS: float = _get_float_env("SESSION_RECOVERY_BONUS", 4.0)
    SESSION_REL_THRESHOLD: float = _get_float_env("SESSION_REL_THRESHOLD", 2.0)
    SESSION_REL_BONUS: float = _get_float_env("SESSION_REL_BONUS", 3.0)
    SESSION_PACE_MIN: float = _get_float_env("SESSION_PACE_MIN", 1.5)
    SESSION_PACE_BONUS: float = _get_float_env("SESSION_PACE_BONUS", 2.0)
    SESSION_BREADTH_MIN_PCT: float = _get_float_env("SESSION_BREADTH_MIN_PCT", 40.0)
    SESSION_BREADTH_PENALTY: float = _get_float_env("SESSION_BREADTH_PENALTY", 4.0)
    SESSION_MAX_BONUS: float = _get_float_env("SESSION_MAX_BONUS", 8.0)
    SESSION_MAX_PENALTY: float = _get_float_env("SESSION_MAX_PENALTY", 8.0)
    SESSION_LIMIT_PCT: float = _get_float_env("SESSION_LIMIT_PCT", 9.5)
    RSI_PERIOD: int = _get_int_env("RSI_PERIOD", 14)
    RSI_OVERSOLD: int = _get_int_env("RSI_OVERSOLD", 30)
    RSI_OVERBOUGHT: int = _get_int_env("RSI_OVERBOUGHT", 70)
    SMA_FAST: int = _get_int_env("SMA_FAST", 5)
    SMA_SLOW: int = _get_int_env("SMA_SLOW", 20)
    EMA_FAST: int = _get_int_env("EMA_FAST", 12)
    EMA_SLOW: int = _get_int_env("EMA_SLOW", 26)
    EMA_LONG: int = _get_int_env("EMA_LONG", 200)
    MACD_FAST: int = _get_int_env("MACD_FAST", 12)
    MACD_SLOW: int = _get_int_env("MACD_SLOW", 26)
    MACD_SIGNAL: int = _get_int_env("MACD_SIGNAL", 9)
    BOLLINGER_PERIOD: int = _get_int_env("BOLLINGER_PERIOD", 20)
    BOLLINGER_STD: float = _get_float_env("BOLLINGER_STD", 2.0)
    ADX_THRESHOLD: int = _get_int_env("ADX_THRESHOLD", 20)
    # Aşama 1: osilatör bölge eşikleri + skor cap'leri + rejim sabitleri
    # (StrategyParams üzerinden tüketilir; indikatör hesaplama pencereleri
    # dahil). Default'lar kodda doğrulanan mevcut değerlerdir.
    STOCH_K_PERIOD: int = _get_int_env("STOCH_K_PERIOD", 14)
    STOCH_D_PERIOD: int = _get_int_env("STOCH_D_PERIOD", 3)
    STOCH_OVERSOLD: float = _get_float_env("STOCH_OVERSOLD", 20.0)
    STOCH_OVERBOUGHT: float = _get_float_env("STOCH_OVERBOUGHT", 80.0)
    STOCH_TREND_MID: float = _get_float_env("STOCH_TREND_MID", 50.0)
    ADX_PERIOD: int = _get_int_env("ADX_PERIOD", 14)
    ATR_PERIOD: int = _get_int_env("ATR_PERIOD", 14)
    OBV_SMA_PERIOD: int = _get_int_env("OBV_SMA_PERIOD", 20)
    BB_SQUEEZE_PERIOD: int = _get_int_env("BB_SQUEEZE_PERIOD", 20)
    BB_SQUEEZE_RATIO: float = _get_float_env("BB_SQUEEZE_RATIO", 0.7)
    BB_PCT_LOW: float = _get_float_env("BB_PCT_LOW", 0.2)
    BB_PCT_HIGH: float = _get_float_env("BB_PCT_HIGH", 0.8)
    CCI_MIN: float = _get_float_env("CCI_MIN", -50.0)
    CCI_MAX: float = _get_float_env("CCI_MAX", 50.0)
    ADX_STRONG_EDGE: float = _get_float_env("ADX_STRONG_EDGE", 25.0)
    SR_DISTANCE_PCT: float = _get_float_env("SR_DISTANCE_PCT", 2.0)
    MOMENTUM_SCORE_CAP: float = _get_float_env("MOMENTUM_SCORE_CAP", 45.0)
    TREND_SCORE_CAP: float = _get_float_env("TREND_SCORE_CAP", 70.0)
    VOLUME_SCORE_CAP: float = _get_float_env("VOLUME_SCORE_CAP", 26.0)
    STRUCTURE_SCORE_CAP: float = _get_float_env("STRUCTURE_SCORE_CAP", 50.0)
    REGIME_LOOKBACK: int = _get_int_env("REGIME_LOOKBACK", 20)
    REGIME_MIN_BARS: int = _get_int_env("REGIME_MIN_BARS", 50)
    REGIME_TREND_ADX: float = _get_float_env("REGIME_TREND_ADX", 20.0)
    REGIME_WEAK_ADX: float = _get_float_env("REGIME_WEAK_ADX", 15.0)
    REGIME_DI_RATIO: float = _get_float_env("REGIME_DI_RATIO", 1.25)
    REGIME_MOMENTUM_PCT: float = _get_float_env("REGIME_MOMENTUM_PCT", 3.0)
    AGREEMENT_FULL: float = _get_float_env("AGREEMENT_FULL", 0.75)
    AGREEMENT_MIN: float = _get_float_env("AGREEMENT_MIN", 0.5)
    AGREEMENT_DIVISOR: float = _get_float_env("AGREEMENT_DIVISOR", 4.0)
    VOLUME_CONFIRM_MULTIPLIER: float = _get_float_env("VOLUME_CONFIRM_MULTIPLIER", 1.5)
    VOLUME_SPIKE_MULTIPLIER: float = _get_float_env("VOLUME_SPIKE_MULTIPLIER", 1.5)
    VOLUME_CONFIRM_TICKER_OVERRIDES: dict[str, float] = field(
        default_factory=lambda: {
            "SASA.IS": 1.2,
            "EREGL.IS": 1.2,
            "KRDMD.IS": 1.2,
            "THYAO.IS": 1.8,
            "GARAN.IS": 1.8,
            "AKBNK.IS": 1.8,
        }
    )
    WALKFORWARD_TRAIN_DAYS: int = _get_int_env("WALKFORWARD_TRAIN_DAYS", 180)
    WALKFORWARD_TEST_DAYS: int = _get_int_env("WALKFORWARD_TEST_DAYS", 30)
    SECTOR_LIMIT: int = _get_int_env("SECTOR_LIMIT", 2)
    INITIAL_CAPITAL: float = _get_float_env("INITIAL_CAPITAL", 100000.0)
    PAPER_MODE: bool = _get_bool_env("PAPER_MODE", False)
    PAPER_TRADES_TABLE: str = _get_table_name_env("PAPER_TRADES_TABLE", "paper_trades")
    OUTCOME_TRACKING_ENABLED: bool = _get_bool_env("OUTCOME_TRACKING_ENABLED", True)
    SHADOW_ENABLED: bool = _get_bool_env("SHADOW_ENABLED", True)
    SHADOW_HOLDING_DAYS: int = _get_int_env("SHADOW_HOLDING_DAYS", 5)
    SHADOW_ONLY_ROBUST: bool = _get_bool_env("SHADOW_ONLY_ROBUST", False)
    SHADOW_MIN_SCORE: int = _get_int_env("SHADOW_MIN_SCORE", 20)
    SHADOW_COOLDOWN_DAYS: int = _get_int_env("SHADOW_COOLDOWN_DAYS", 2)
    # Sprint 1: daily-report RADAR listing budget (gate-demoted + tier A + tier B combined).
    RADAR_REPORT_TOP_N: int = _get_int_env("RADAR_REPORT_TOP_N", 50)
    COMMISSION_BUY: float = _get_float_env("COMMISSION_BUY", 0.0002)
    COMMISSION_SELL: float = _get_float_env("COMMISSION_SELL", 0.0002)
    BSMV: float = _get_float_env("BSMV", 0.0005)
    SLIPPAGE: float = _get_float_env("SLIPPAGE", 0.001)
    SLIPPAGE_PCT: float = _get_float_env("SLIPPAGE_PCT", 0.001)
    SLIPPAGE_PENALTY_RATIO: float = _get_float_env("SLIPPAGE_PENALTY_RATIO", 0.15)
    SLIPPAGE_MAX_CAP: float = _get_float_env("SLIPPAGE_MAX_CAP", 0.02)


@dataclass(frozen=True)
class RiskSettings:
    CORRELATION_THRESHOLD: float = _get_float_env("CORRELATION_THRESHOLD", 0.70)
    CORRELATION_RISK_STEP: float = _get_float_env("CORRELATION_RISK_STEP", 0.35)
    CORRELATION_MIN_SCALE: float = _get_float_env("CORRELATION_MIN_SCALE", 0.25)
    CORRELATION_MAX_CLUSTER: int = _get_int_env("CORRELATION_MAX_CLUSTER", 2)
    ATR_BASELINE_PCT: float = _get_float_env("ATR_BASELINE_PCT", 0.025)
    ATR_MIN_RISK_SCALE: float = _get_float_env("ATR_MIN_RISK_SCALE", 0.35)
    MAX_POSITION_CAP_PCT: float = _get_float_env("MAX_POSITION_CAP_PCT", 5.0)
    MAX_SECTOR_CAP_PCT: float = _get_float_env("MAX_SECTOR_CAP_PCT", 20.0)
    MAX_TOTAL_RISK_PCT: float = _get_float_env("MAX_TOTAL_RISK_PCT", 2.0)
    KELLY_FRACTION_SCALE: float = _get_float_env("KELLY_FRACTION_SCALE", 0.25)
    MIN_SIGNAL_PROBABILITY: float = _get_float_env("MIN_SIGNAL_PROBABILITY", 0.50)
    MIN_LIQUIDITY_VALUE_TL: float = _get_float_env("MIN_LIQUIDITY_VALUE_TL", 5_000_000.0)
    DAILY_LOSS_CAP_PCT: float = _get_float_env("DAILY_LOSS_CAP_PCT", 3.0)
    MIN_STOP_LOSS_PCT: float = _get_float_env("MIN_STOP_LOSS_PCT", 1.8)
    ATR_TARGET_FLOOR_PCT: float = _get_float_env("ATR_TARGET_FLOOR_PCT", 2.0)
    # Champion profili RR 0.5 ile doğrulandı (küçük hedef, yüksek isabet).
    # Varsayılan, champion canlı konfigürasyonuyla aynı tutulur.
    FALLBACK_TARGET_RR: float = _get_float_env("FALLBACK_TARGET_RR", 0.5)
    MAX_SIGNAL_SCORE: float = _get_float_env("MAX_SIGNAL_SCORE", 33.0)
    # Aşama 1: pairwise korelasyon fallback'i için minimum örtüşen bar sayısı
    # (risk/correlation.get_correlated_positions). Default kodda doğrulanan 10.
    CORR_FALLBACK_MIN_BARS: int = _get_int_env("CORR_FALLBACK_MIN_BARS", 10)
    ATR_TARGET_MULT: float = _get_float_env("ATR_TARGET_MULT", 1.5)


@dataclass(frozen=True)
class DataSettings:
    DATA_PERIOD: str = _get_str_env("DATA_PERIOD", "3mo")
    DATA_INTERVAL: str = _get_str_env("DATA_INTERVAL", "1d")
    DATA_PROVIDER: str = _get_str_env("DATA_PROVIDER", "yfinance").lower()
    MTF_ENABLED: bool = _get_bool_env("MTF_ENABLED", True)
    MTF_TREND_PERIOD: str = _get_str_env("MTF_TREND_PERIOD", "6mo")
    MTF_TREND_INTERVAL: str = _get_str_env("MTF_TREND_INTERVAL", "1d")
    MTF_TRIGGER_PERIOD: str = _get_str_env("MTF_TRIGGER_PERIOD", "1mo")
    MTF_TRIGGER_INTERVAL: str = _get_str_env("MTF_TRIGGER_INTERVAL", "15m")
    ENABLE_REALTIME_SCRAPING: bool = _get_bool_env("ENABLE_REALTIME_SCRAPING", True)
    RATE_LIMIT_SECONDS: float = _get_float_env("RATE_LIMIT_SECONDS", 2.0)
    FETCH_CACHE_TTL_SECONDS: float = _get_float_env("FETCH_CACHE_TTL_SECONDS", 900.0)
    INTRADAY_FETCH_CACHE_TTL_SECONDS: float = _get_float_env(
        "INTRADAY_FETCH_CACHE_TTL_SECONDS", 120.0
    )
    ANALYSIS_CACHE_TTL_SECONDS: float = _get_float_env("ANALYSIS_CACHE_TTL_SECONDS", 180.0)
    REALTIME_QUOTE_CACHE_TTL_SECONDS: float = _get_float_env(
        "REALTIME_QUOTE_CACHE_TTL_SECONDS", 30.0
    )
    OFFICIAL_VENDOR: str = _get_str_env("OFFICIAL_VENDOR", "generic").lower()
    OFFICIAL_API_BASE_URL: str = _get_str_env("OFFICIAL_API_BASE_URL")
    OFFICIAL_API_KEY: str = _get_str_env("OFFICIAL_API_KEY")
    OFFICIAL_USERNAME: str = _get_str_env("OFFICIAL_USERNAME")
    OFFICIAL_PASSWORD: str = _get_str_env("OFFICIAL_PASSWORD")
    OFFICIAL_TIMEOUT: float = _get_float_env("OFFICIAL_TIMEOUT", 30.0)
    OFFICIAL_MAX_RETRIES: int = _get_int_env("OFFICIAL_MAX_RETRIES", 3)
    OFFICIAL_RETRY_BACKOFF_SECONDS: float = _get_float_env("OFFICIAL_RETRY_BACKOFF_SECONDS", 1.0)
    OFFICIAL_MAX_RETRY_SLEEP_SECONDS: float = _get_float_env(
        "OFFICIAL_MAX_RETRY_SLEEP_SECONDS", 2.0
    )
    OFFICIAL_AUTH_ENDPOINT: str = _get_str_env("OFFICIAL_AUTH_ENDPOINT")
    OFFICIAL_HISTORY_ENDPOINT: str = _get_str_env("OFFICIAL_HISTORY_ENDPOINT")
    OFFICIAL_BATCH_ENDPOINT: str = _get_str_env("OFFICIAL_BATCH_ENDPOINT")
    OFFICIAL_QUOTE_ENDPOINT: str = _get_str_env("OFFICIAL_QUOTE_ENDPOINT")
    OFFICIAL_UNIVERSE_ENDPOINT: str = _get_str_env("OFFICIAL_UNIVERSE_ENDPOINT")
    BENCHMARK_TICKER: str = _get_str_env("BENCHMARK_TICKER", "^XU100")
    BENCHMARK_TICKER_ALT: str = _get_str_env("BENCHMARK_TICKER_ALT", "XRXIST.IS")
    DATA_PROVIDER_FALLBACK_ORDER: str = _get_str_env("DATA_PROVIDER_FALLBACK_ORDER", "")
    FAILOVER_FAILURE_THRESHOLD: int = _get_int_env("FAILOVER_FAILURE_THRESHOLD", 3)
    FAILOVER_COOLDOWN_SECONDS: float = _get_float_env("FAILOVER_COOLDOWN_SECONDS", 60.0)
    STAMP_TAX: float = _get_float_env("STAMP_TAX", 0.00093)
    EXCHANGE_FEE: float = _get_float_env("EXCHANGE_FEE", 0.0005)
    SCRAPER_REQUEST_TIMEOUT_SECONDS: int = _get_int_env("SCRAPER_REQUEST_TIMEOUT_SECONDS", 10)
    PROVIDER_BATCH_TIMEOUT_SECONDS: int = _get_int_env("PROVIDER_BATCH_TIMEOUT_SECONDS", 60)
    PROVIDER_SINGLE_TIMEOUT_SECONDS: int = _get_int_env("PROVIDER_SINGLE_TIMEOUT_SECONDS", 10)
    YFINANCE_MAX_RETRIES: int = _get_int_env("YFINANCE_MAX_RETRIES", 3)
    YFINANCE_RETRY_BACKOFF_SECONDS: float = _get_float_env("YFINANCE_RETRY_BACKOFF_SECONDS", 1.0)
    YFINANCE_MAX_RETRY_SLEEP_SECONDS: float = _get_float_env(
        "YFINANCE_MAX_RETRY_SLEEP_SECONDS", 2.0
    )


@dataclass(frozen=True)
class DatabaseSettings:
    DATABASE_URL: str = _get_str_env("DATABASE_URL")
    # nosec B108: Cloud Run ephemeral default; override via DB_PATH/DATABASE_URL.
    DB_PATH: str = _get_str_env("DB_PATH", "/tmp/bist_signals.db")  # nosec B108


@dataclass(frozen=True)
class AuthSettings:
    JWT_SECRET_KEY: str = _get_str_env("JWT_SECRET_KEY")
    # AppSec (Round 10): Flask session signing key, separated from the JWT key.
    # Empty default preserves legacy behavior (falls back to JWT_SECRET_KEY);
    # set SECRET_KEY in production for signing-domain separation.
    SECRET_KEY: str = _get_str_env("SECRET_KEY")
    JWT_ACCESS_TOKEN_MINUTES: int = _get_int_env("JWT_ACCESS_TOKEN_MINUTES", 15)
    RBAC_MODE: str = _get_str_env("RBAC_MODE", "warn").lower()
    ADMIN_BOOTSTRAP_EMAIL: str = _get_str_env("ADMIN_BOOTSTRAP_EMAIL")
    ADMIN_BOOTSTRAP_PASSWORD_HASH: str = _get_str_env("ADMIN_BOOTSTRAP_PASSWORD_HASH")
    ADMIN_BOOTSTRAP_UPDATE_EXISTING: bool = _get_bool_env("ADMIN_BOOTSTRAP_UPDATE_EXISTING", False)
    JWT_COOKIE_SECURE: bool = _get_bool_env("JWT_COOKIE_SECURE", False)
    ALLOW_PUBLIC_REGISTRATION: bool = _get_bool_env("ALLOW_PUBLIC_REGISTRATION", False)
    CORS_ORIGINS: tuple[str, ...] = field(default_factory=lambda: _get_csv_env("CORS_ORIGINS"))


@dataclass(frozen=True)
class ServerSettings:
    FLASK_PORT: int = DEFAULT_FLASK_PORT
    FLASK_DEBUG: bool = _get_bool_env("FLASK_DEBUG", False)
    LOG_FORMAT: str = _get_str_env("LOG_FORMAT", "console")
    LOG_LEVEL: str = _get_str_env("LOG_LEVEL", "INFO")
    METRICS_PUBLIC: bool = _get_bool_env("METRICS_PUBLIC", False)
    API_BASE_URL: str = _get_str_env("API_BASE_URL", f"http://localhost:{DEFAULT_FLASK_PORT}")
    RATE_LIMIT_STORAGE_URI: str = _get_str_env("RATE_LIMIT_STORAGE_URI", "memory://")
    # AppSec finding #21: number of trusted reverse-proxy hops that rewrite
    # X-Forwarded-For. 0 (default) = remote_addr stays the TCP peer (current,
    # spoof-proof behavior). >0 enables werkzeug ProxyFix in wsgi.py so
    # remote_addr is derived from the rightmost XFF entry. ONLY set to 1 on
    # Cloud Run AFTER a live request confirms the XFF chain (see
    # docs/security/phase0_phase1_report.md). Never set on direct-client
    # deployments (compose/local) — clients could spoof their IP.
    TRUSTED_PROXY_HOPS: int = _get_int_env("TRUSTED_PROXY_HOPS", 0)
    EXPECTED_INSTANCE_COUNT: int = _get_int_env("EXPECTED_INSTANCE_COUNT", 1)
    DEGRADED_MAX_SECONDS: int = _get_int_env("DEGRADED_MAX_SECONDS", 300)
    SENTRY_DSN: str | None = _get_str_env("SENTRY_DSN") or None
    ENVIRONMENT: str = _get_str_env("ENVIRONMENT", "production")
    SCAN_TIMEOUT_SECONDS: int = _get_int_env("SCAN_TIMEOUT_SECONDS", 300)
    SCAN_API_TIMEOUT_SECONDS: float = _get_float_env("SCAN_API_TIMEOUT_SECONDS", 300.0)
    STREAMLIT_SCAN_COOLDOWN_SECONDS: float = _get_float_env("STREAMLIT_SCAN_COOLDOWN_SECONDS", 8.0)
    STREAMLIT_ANALYZE_COOLDOWN_SECONDS: float = _get_float_env(
        "STREAMLIT_ANALYZE_COOLDOWN_SECONDS", 4.0
    )
    STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS: int = _get_int_env(
        "STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS", 300
    )
    API_REQUEST_TIMEOUT_SECONDS: int = _get_int_env("API_REQUEST_TIMEOUT_SECONDS", 30)
    SCAN_INTERVAL_MINUTES: int = _get_int_env("SCAN_INTERVAL_MINUTES", 15)
    MARKET_OPEN_HOUR: int = _get_int_env("MARKET_OPEN_HOUR", 10)
    MARKET_CLOSE_HOUR: int = _get_int_env("MARKET_CLOSE_HOUR", 18)
    MARKET_WARMUP_MINUTES: int = _get_int_env("MARKET_WARMUP_MINUTES", 15)
    MARKET_HALF_DAY_HOUR: int = _get_int_env("MARKET_HALF_DAY_HOUR", 13)
    # BIST: continuous trading ends at MARKET_CLOSE_HOUR; the closing/single-price
    # session runs SESSION_CLOSE_BUFFER_MINUTES longer (18:00-18:10). EOD pass
    # triggers at session close + EOD_CLOSE_DELAY_MINUTES (~18:12 default).
    SESSION_CLOSE_BUFFER_MINUTES: int = _get_int_env("SESSION_CLOSE_BUFFER_MINUTES", 10)
    EOD_CLOSE_DELAY_MINUTES: int = _get_int_env("EOD_CLOSE_DELAY_MINUTES", 2)
    EOD_MAX_ATTEMPTS: int = _get_int_env("EOD_MAX_ATTEMPTS", 2)
    EOD_RETRY_MINUTES: int = _get_int_env("EOD_RETRY_MINUTES", 8)
    # C3 watchdog: alert when no successful scan for this long during market hours.
    WATCHDOG_STALE_MINUTES: int = _get_int_env("WATCHDOG_STALE_MINUTES", 30)
    WATCHDOG_ALERT_COOLDOWN_MINUTES: int = _get_int_env("WATCHDOG_ALERT_COOLDOWN_MINUTES", 60)
    # C5: minimum spacing between consecutive scans (startup scan vs next grid slot).
    SCAN_MIN_SEPARATION_MINUTES: int = _get_int_env("SCAN_MIN_SEPARATION_MINUTES", 5)
    # B3: alert after this many consecutive price misses for an open paper trade.
    PAPER_CLOSE_SKIP_WARN_THRESHOLD: int = _get_int_env("PAPER_CLOSE_SKIP_WARN_THRESHOLD", 5)
    # B4: candle freshness gate — max trigger-bar age during market hours and
    # stale-ratio bands (warn publishes a daily warning; halt aborts the scan).
    STALE_BAR_MAX_AGE_MINUTES: int = _get_int_env("STALE_BAR_MAX_AGE_MINUTES", 30)
    STALE_SYMBOL_WARN_RATIO: float = _get_float_env("STALE_SYMBOL_WARN_RATIO", 0.20)
    STALE_SYMBOL_HALT_RATIO: float = _get_float_env("STALE_SYMBOL_HALT_RATIO", 0.40)
    # Cooldown between stale-halt Telegram alerts (halt recurs every scan otherwise).
    STALE_HALT_ALERT_COOLDOWN_MINUTES: int = _get_int_env("STALE_HALT_ALERT_COOLDOWN_MINUTES", 120)
    METRICS_ALLOWED_IPS: tuple[str, ...] = field(
        default_factory=lambda: _get_csv_env("METRICS_ALLOWED_IPS")
    )


@dataclass(frozen=True)
class BrokerSettings:
    BROKER_MODE: str = _get_str_env("BROKER_MODE", "paper").lower()
    BROKER_PROVIDER: str = _get_str_env("BROKER_PROVIDER", "paper").lower()
    WATCHLIST_SOURCE: str = _get_str_env("WATCHLIST_SOURCE", "bist100")
    ALGOLAB_API_KEY: str = _get_str_env("ALGOLAB_API_KEY")
    ALGOLAB_USERNAME: str = _get_str_env("ALGOLAB_USERNAME")
    ALGOLAB_PASSWORD: str = _get_str_env("ALGOLAB_PASSWORD")
    ALGOLAB_OTP_CODE: str = _get_str_env("ALGOLAB_OTP_CODE")
    ALGOLAB_DRY_RUN: bool = _get_bool_env("ALGOLAB_DRY_RUN", True)
    ALGOLAB_SEND_CLIENT_ID: bool = _get_bool_env("ALGOLAB_SEND_CLIENT_ID", False)
    ALGOLAB_LOGIN_URL: str = _get_str_env("ALGOLAB_LOGIN_URL")
    ALGOLAB_VERIFY_OTP_URL: str = _get_str_env("ALGOLAB_VERIFY_OTP_URL")
    ALGOLAB_POSITIONS_URL: str = _get_str_env("ALGOLAB_POSITIONS_URL")
    ALGOLAB_ACCOUNT_URL: str = _get_str_env("ALGOLAB_ACCOUNT_URL")
    ALGOLAB_ORDERS_URL: str = _get_str_env("ALGOLAB_ORDERS_URL")
    ALGOLAB_ORDER_STATUS_URL: str = _get_str_env("ALGOLAB_ORDER_STATUS_URL")
    ALGOLAB_CANCEL_ORDER_URL: str = _get_str_env("ALGOLAB_CANCEL_ORDER_URL")
    ALGOLAB_OPEN_ORDERS_URL: str = _get_str_env("ALGOLAB_OPEN_ORDERS_URL")
    ALGOLAB_ORDER_HISTORY_URL: str = _get_str_env("ALGOLAB_ORDER_HISTORY_URL")
    ALGOLAB_RECONCILE_WINDOW_SECONDS: int = _get_int_env("ALGOLAB_RECONCILE_WINDOW_SECONDS", 180)
    ALGOLAB_RECONCILE_ON_STARTUP: bool = _get_bool_env("ALGOLAB_RECONCILE_ON_STARTUP", True)
    ALGOLAB_RECONCILE_CANCEL_REMAINDER: bool = _get_bool_env(
        "ALGOLAB_RECONCILE_CANCEL_REMAINDER", True
    )
    ALGOLAB_STATUS_MAP: str = _get_str_env("ALGOLAB_STATUS_MAP", "")
    ALPACA_API_KEY: str = _get_str_env("ALPACA_API_KEY")
    ALPACA_SECRET_KEY: str = _get_str_env("ALPACA_SECRET_KEY")
    ALPACA_PAPER: bool = _get_bool_env("ALPACA_PAPER", True)
    ALPACA_DRY_RUN: bool = _get_bool_env("ALPACA_DRY_RUN", False)
    # Deney J (docs/retail_abone_ekonomisi.md §Deney J): 8 slots x 12.5% beats
    # 5 x 20% on every subscriber metric on the live BIST100 universe
    # (+2,350 vs +1,538 TL/mo, 64% vs 50% positive months, worst month and DD
    # roughly halved). Diversification, not concentration, is the edge here.
    MAX_OPEN_POSITIONS: int = _get_int_env("MAX_OPEN_POSITIONS", 8)
    MAX_POSITION_SIZE: float = _get_float_env("MAX_POSITION_SIZE", 0.125)
    MAX_DAILY_LOSS: float = _get_float_env("MAX_DAILY_LOSS", 0.03)
    MAX_ACCOUNT_DRAWDOWN: float = _get_float_env("MAX_ACCOUNT_DRAWDOWN", 0.15)
    AUTO_EXECUTE_ENABLED: bool = _get_bool_env("AUTO_EXECUTE_ENABLED", False)
    AUTO_EXECUTE: bool = _get_bool_env("AUTO_EXECUTE", False)
    # Varsayılan canlı profil: champion (challenge 2026-08-29 — %76.4 WR,
    # skor bandı 28-33, pv-gate). Eski davranış için STRATEGY_PROFILE=conservative.
    STRATEGY_PROFILE: str = _get_str_env("STRATEGY_PROFILE", "champion")
    CONFIRM_LIVE_TRADING: bool = _get_bool_env("CONFIRM_LIVE_TRADING", False)
    AUTO_EXECUTE_WARN_MAX_QUANTITY: int = _get_int_env("AUTO_EXECUTE_WARN_MAX_QUANTITY", 100000)


@dataclass(frozen=True)
class BacktestSettings:
    BACKTEST_COMMISSION_PCT: float = _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    BACKTEST_COMMISSION_BUY_PCT: float = _get_float_env(
        "BACKTEST_COMMISSION_BUY_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    )
    BACKTEST_COMMISSION_SELL_PCT: float = _get_float_env(
        "BACKTEST_COMMISSION_SELL_PCT", _get_float_env("BACKTEST_COMMISSION_PCT", 0.001)
    )
    BACKTEST_SLIPPAGE_PCT: float = _get_float_env("BACKTEST_SLIPPAGE_PCT", 0.0005)
    # v2 toparlama planı §3: gerçekçi (live-like) replay senaryosu varsayımları.
    # Yalnızca "realistic" senaryoyu besler; base/zero/stress değişmez.
    BACKTEST_REALISTIC_COMMISSION_BPS: float = _get_float_env(
        "BACKTEST_REALISTIC_COMMISSION_BPS", 15.0
    )
    BACKTEST_REALISTIC_SPREAD_BPS: float = _get_float_env("BACKTEST_REALISTIC_SPREAD_BPS", 20.0)
    BACKTEST_REALISTIC_SLIPPAGE_BPS: float = _get_float_env("BACKTEST_REALISTIC_SLIPPAGE_BPS", 30.0)
    BACKTEST_REALISTIC_ENTRY_DELAY_BARS: int = _get_int_env(
        "BACKTEST_REALISTIC_ENTRY_DELAY_BARS", 1
    )
    BACKTEST_REALISTIC_MIN_VOLUME_TRY: float = _get_float_env(
        "BACKTEST_REALISTIC_MIN_VOLUME_TRY", 100_000.0
    )
    BACKTEST_REALISTIC_MAX_PARTICIPATION_PCT: float = _get_float_env(
        "BACKTEST_REALISTIC_MAX_PARTICIPATION_PCT", 1.0
    )
    BACKTEST_REALISTIC_FILL_PROBABILITY: float = _get_float_env(
        "BACKTEST_REALISTIC_FILL_PROBABILITY", 0.95
    )
    # Aşama 3: True iken vektör yol zorla kapatılır (debug/test).
    # Default False -> mevcut yol seçimi korunur.
    BACKTEST_FORCE_ITERATIVE: bool = _get_bool_env("BACKTEST_FORCE_ITERATIVE", False)


@dataclass(frozen=True)
class MLSettings:
    CALIBRATOR_TRUST: str = _get_str_env("CALIBRATOR_TRUST", "warn").lower()
    MODEL_SIGNING_PRIVATE_KEY_FILE: str = _get_str_env("MODEL_SIGNING_PRIVATE_KEY_FILE")
    MODEL_VERIFY_PUBLIC_KEY_FILE: str = _get_str_env("MODEL_VERIFY_PUBLIC_KEY_FILE")
    ML_SEQUENCE_LENGTH: int = _get_int_env("ML_SEQUENCE_LENGTH", 60)
    ML_EPOCHS: int = _get_int_env("ML_EPOCHS", 50)
    ML_BATCH_SIZE: int = _get_int_env("ML_BATCH_SIZE", 32)
    ML_MODEL_PATH: str = _get_str_env("ML_MODEL_PATH", "models")


@dataclass(frozen=True)
class AgentSettings:
    # Agent path (live_positions book) owns the multi-day strategy the
    # backtests optimize (mh28 ~ 20 trading sessions, 8 slots, risk parity).
    # Enabled by default since the max-income activation (Deney M: trail3).
    AGENT_ENABLED: bool = _get_bool_env("AGENT_ENABLED", True)
    EMERGENCY_CLOSE_ON_HALT: bool = _get_bool_env("EMERGENCY_CLOSE_ON_HALT", False)
    # Keep in sync with BrokerSettings.MAX_OPEN_POSITIONS (Deney J: 8 slots).
    MAX_OPEN_POSITIONS: int = _get_int_env("MAX_OPEN_POSITIONS", 8)
    MAX_DAILY_TRADES: int = _get_int_env("MAX_DAILY_TRADES", 10)
    POSITION_MONITOR_ENABLED: bool = _get_bool_env("POSITION_MONITOR_ENABLED", False)
    POSITION_CHECK_INTERVAL_SECONDS: int = _get_int_env("POSITION_CHECK_INTERVAL_SECONDS", 60)
    # Deney M (docs/retail_abone_ekonomisi.md §17): ATR trailing stop
    # (peak_close - k * ATR14) dominates the fixed stop at every DD level;
    # k=3.0 is the optimum. TRAILING_STOP_PCT is legacy (percent trail, only
    # used by paths that set it explicitly); the agent book uses the ATR trail.
    TRAILING_STOP_ENABLED: bool = _get_bool_env("TRAILING_STOP_ENABLED", True)
    TRAILING_ATR_MULT: float = _get_float_env("TRAILING_ATR_MULT", 3.0)
    TRAILING_STOP_PCT: float = _get_float_env("TRAILING_STOP_PCT", 2.0)
    # Entry score floor for the agent book. Entries are already restricted to
    # STRONG_BUY (score >= STRONG_BUY_THRESHOLD = 48) by _entry_signal_types,
    # so the default 0 trusts the signal engine's own gating; raise it via env
    # to require higher-confidence entries.
    MIN_SCORE_THRESHOLD: int = _get_int_env("MIN_SCORE_THRESHOLD", 0)
    # Calendar-day hold limit for live positions (position_manager counts
    # (now - entry_time).days). 28 calendar days ~= 20 trading sessions, which
    # matched the best per-signal/portfolio economics in Deney H analysis
    # (docs/retail_abone_ekonomisi.md). The previous default 5 calendar days
    # ~= 3 trading sessions forced exits before targets could develop.
    MAX_HOLDING_DAYS: int = _get_int_env("MAX_HOLDING_DAYS", 28)
    RESTART_RECOVERY_ENABLED: bool = _get_bool_env("RESTART_RECOVERY_ENABLED", False)
    EXIT_ORDER_TYPE: str = _get_str_env("EXIT_ORDER_TYPE", "MARKET")
    AUDIT_LOG_ENABLED: bool = _get_bool_env("AUDIT_LOG_ENABLED", False)


@dataclass(frozen=True)
class NotificationSettings:
    TELEGRAM_BOT_TOKEN: str = _get_str_env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = _get_str_env("TELEGRAM_CHAT_ID")
    TELEGRAM_MIN_SCORE: int = _get_int_env(
        "TELEGRAM_MIN_SCORE", _get_int_env("STRONG_BUY_THRESHOLD", 48)
    )
    TELEGRAM_GROUP_CHAT_ID: str = _get_str_env("TELEGRAM_GROUP_CHAT_ID")
    # Master switch for group mirroring. Historically a non-empty chat id alone
    # enabled dispatch; this flag now gates it (default True keeps old behavior
    # for deployments that only set the chat id).
    TELEGRAM_GROUP_ENABLED: bool = _get_bool_env("TELEGRAM_GROUP_ENABLED", True)
    TELEGRAM_GROUP_MIN_SCORE: int = _get_int_env(
        "TELEGRAM_GROUP_MIN_SCORE", _get_int_env("STRONG_BUY_THRESHOLD", 48)
    )
    # Deprecated: score-based group threshold is no longer used for dispatch.
    # Group routing now uses robust-watchlist membership (load_watchlist("robust")).
    # Kept for backward compatibility only.
    NOTIFICATION_MAX_RETRIES: int = _get_int_env("NOTIFICATION_MAX_RETRIES", 3)
    TELEGRAM_GROUP_BATCH_THRESHOLD: int = _get_int_env("TELEGRAM_GROUP_BATCH_THRESHOLD", 5)
    NOTIFICATION_RETRY_DELAY: int = _get_int_env("NOTIFICATION_RETRY_DELAY", 5)
    # Global Telegram send-rate safety budget (messages per minute) enforced by a
    # sliding-window limiter. Bots are capped at ~30 msg/min per bot; 18 keeps
    # headroom for both owner and group traffic without tripping 429s.
    TELEGRAM_RATE_LIMIT_PER_MINUTE: int = _get_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 18)
    # How long a generated signal remains fresh/actionable (minutes).
    # Signals older than this are marked expired and skipped for notifications.
    SIGNAL_TTL_MINUTES: int = _get_int_env("SIGNAL_TTL_MINUTES", 60)
    # Minimum score movement required for a user-facing signal-change
    # notification when neither the old nor the new signal is actionable.
    # 0 = legacy behaviour (notify on every signal-type change).
    # Valid range 0-100 (score is bounded ±100).
    SIGNAL_CHANGE_MIN_SCORE_DELTA: int = max(
        0, min(100, _get_int_env("SIGNAL_CHANGE_MIN_SCORE_DELTA", 15))
    )
    # AL-signal per-ticker cooldown (minutes). A ticker that already produced
    # an actionable buy-family signal within this window will not persist a
    # new AL signal (notifications/tracking still see the full list).
    # 0 disables the cooldown (legacy behaviour).
    AL_SIGNAL_COOLDOWN_MINUTES: int = max(0, _get_int_env("AL_SIGNAL_COOLDOWN_MINUTES", 60))


@dataclass(frozen=True)
class BillingSettings:
    """Membership subscription + manual EFT/havale billing configuration."""

    # FAIL-CLOSED satış anahtarı (2026-09-17): canlı sinyal kanıtı zayıfken
    # (n=45 → WR %33.3, skor↔PnL r=0.147, net -1.695 TL) ücretli abonelik
    # satışı DURAKLATILDI. Yeniden açmak için env'e explicitly true verin:
    # kanıt eşiği = signal_outcomes n>=100 ve WR backtest'e yakınsaması.
    # Deneme (trial) kayıtları bu anahtardan etkilenmez.
    BILLING_ENROLLMENT_ENABLED: bool = _get_bool_env("BILLING_ENROLLMENT_ENABLED", False)
    # Trial granted on registration (and to pre-existing users at migration).
    TRIAL_HOURS: int = _get_int_env("TRIAL_HOURS", 24)
    # Paid plan prices (integer TL, backend-authoritative — never trusted from
    # the client) and subscription duration in days.
    PRO_PRICE_TRY: int = _get_int_env("PRO_PRICE_TRY", 500)
    PRO_PLUS_PRICE_TRY: int = _get_int_env("PRO_PLUS_PRICE_TRY", 700)
    SUBSCRIPTION_DAYS: int = _get_int_env("SUBSCRIPTION_DAYS", 30)
    # Manual bank transfer destination shown on the billing page.
    BILLING_IBAN: str = _get_str_env("BILLING_IBAN")
    # Pro+ private Telegram channel used for single-use invite links.
    TELEGRAM_PRO_CHANNEL_ID: str = _get_str_env("TELEGRAM_PRO_CHANNEL_ID")
    # Single-use invite link lifetime in hours.
    TELEGRAM_INVITE_HOURS: int = _get_int_env("TELEGRAM_INVITE_HOURS", 48)
