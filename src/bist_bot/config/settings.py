"""Runtime application settings loaded from environment variables."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

# Guard against repeated ``load_dotenv`` calls during ``importlib.reload`` so
# monkeypatched/test values are not silently re-populated from ``.env``.
_DOTENV_FLAG = "_bist_bot_dotenv_loaded"
if load_dotenv is not None and _DOTENV_FLAG not in __import__("sys").modules:
    load_dotenv()
    __import__("sys").modules[_DOTENV_FLAG] = True

from bist_bot.config.subsettings import (  # noqa: E402
    DEFAULT_BIST100_WATCHLIST,
    SECTOR_MAP,
    TICKER_NAMES,
    AgentSettings,
    AuthSettings,
    BacktestSettings,
    BrokerSettings,
    DatabaseSettings,
    DataSettings,
    MLSettings,
    NotificationSettings,
    RiskSettings,
    ServerSettings,
    TradingSettings,
)
from bist_bot.config.watchlist import load_watchlist, resolve_watchlist_source  # noqa: E402


def _default_watchlist_source() -> str:
    return resolve_watchlist_source(None)


def _default_watchlist() -> list[str]:
    return load_watchlist(_default_watchlist_source())


_SETTINGS_MERGED_OVERRIDE: ContextVar[dict[str, Any] | None] = ContextVar(
    "settings_merged_override",
    default=None,
)


class SettingsOverride:
    def __init__(self, settings_obj: Settings, **overrides: Any) -> None:
        valid_fields = settings_obj.__dataclass_fields__
        sub_field_names = set()
        for group_name in _SUB_SETTINGS_GROUPS:
            group = getattr(settings_obj, group_name)
            sub_field_names.update(group.__dataclass_fields__)
        all_valid = set(valid_fields) | sub_field_names
        unknown_fields = sorted(name for name in overrides if name not in all_valid)
        if unknown_fields:
            unknown = ", ".join(unknown_fields)
            raise AttributeError(f"Unknown settings override(s): {unknown}")
        self._overrides = overrides
        self._merged_token: Token[dict[str, Any] | None] | None = None

    def __enter__(self) -> Settings:
        current = _SETTINGS_MERGED_OVERRIDE.get()
        next_merged = dict(current) if current else {}
        next_merged.update(self._overrides)
        self._merged_token = _SETTINGS_MERGED_OVERRIDE.set(next_merged)
        return settings

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._merged_token is not None:
            _SETTINGS_MERGED_OVERRIDE.reset(self._merged_token)
            self._merged_token = None


_SUB_SETTINGS_GROUPS = (
    "trading",
    "risk",
    "data",
    "database",
    "auth",
    "server",
    "broker",
    "backtest",
    "ml",
    "notification",
    "agent",
)


@dataclass(frozen=True)
class Settings:
    DEFAULT_BIST100_WATCHLIST: list[str] = field(
        default_factory=lambda: list(DEFAULT_BIST100_WATCHLIST)
    )
    # "robust" | "bist30" | "bist100" | "file:<path>"  (env: WATCHLIST_SOURCE / BIST_BOT_WATCHLIST_SOURCE)
    WATCHLIST_SOURCE: str = field(default_factory=_default_watchlist_source)
    WATCHLIST: list[str] = field(default_factory=_default_watchlist)
    TICKER_NAMES: dict[str, str] = field(default_factory=lambda: dict(TICKER_NAMES))
    SECTOR_MAP: dict[str, str] = field(default_factory=lambda: dict(SECTOR_MAP))

    trading: TradingSettings = field(default_factory=TradingSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    data: DataSettings = field(default_factory=DataSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    broker: BrokerSettings = field(default_factory=BrokerSettings)
    backtest: BacktestSettings = field(default_factory=BacktestSettings)
    ml: MLSettings = field(default_factory=MLSettings)
    notification: NotificationSettings = field(default_factory=NotificationSettings)

    def __getattribute__(self, name: str) -> Any:
        if not name.startswith("_"):
            merged_overrides = _SETTINGS_MERGED_OVERRIDE.get()
            if merged_overrides is not None and name in merged_overrides:
                return merged_overrides[name]
        if (
            not name.startswith("_")
            and name not in _SETTINGS_FIELD_NAMES
            and name not in _SUB_SETTINGS_GROUPS
        ):
            for group_name in _SUB_SETTINGS_GROUPS:
                group = object.__getattribute__(self, group_name)
                if hasattr(group, name):
                    return getattr(group, name)
        return object.__getattribute__(self, name)

    def override(self, **overrides: Any) -> SettingsOverride:
        return SettingsOverride(self, **overrides)

    def replace(self, **overrides: Any) -> Settings:
        direct_overrides: dict[str, Any] = {}
        sub_overrides: dict[str, dict[str, Any]] = {}
        for key, value in overrides.items():
            if key in self.__dataclass_fields__:
                direct_overrides[key] = value
            else:
                matched = False
                for group_name in _SUB_SETTINGS_GROUPS:
                    group = object.__getattribute__(self, group_name)
                    if hasattr(group, key):
                        sub_overrides.setdefault(group_name, {})[key] = value
                        matched = True
                        break
                if not matched:
                    raise TypeError(f"Unknown settings field: {key}")
        for group_name, group_overrides in sub_overrides.items():
            group = object.__getattribute__(self, group_name)
            direct_overrides[group_name] = dataclass_replace(group, **group_overrides)
        return dataclass_replace(self, **direct_overrides)

    def require_security_config(self) -> None:
        if not self.JWT_SECRET_KEY:
            raise RuntimeError("Missing required security setting(s): JWT_SECRET_KEY")

    @property
    def admin_bootstrap_enabled(self) -> bool:
        return bool(self.ADMIN_BOOTSTRAP_EMAIL and self.ADMIN_BOOTSTRAP_PASSWORD_HASH)

    def validate_broker_config(self) -> None:
        mode = str(getattr(self, "BROKER_MODE", "") or self.BROKER_PROVIDER).lower()
        provider = str(self.BROKER_PROVIDER).lower()
        allowed = {"paper", "live", "algolab"}
        if mode not in allowed and provider not in allowed:
            raise RuntimeError(
                f"Unsupported BROKER_MODE/BROKER_PROVIDER: mode={mode!r} provider={provider!r}"
            )
        # Live stub is intentional; venue adapters require explicit provider.
        if mode == "live" and provider in {"live", "paper"}:
            # LiveBroker stub — allowed for construction; submit raises NotImplementedError.
            return
        if provider == "algolab":
            if not self.ALGOLAB_API_KEY or not self.ALGOLAB_USERNAME or not self.ALGOLAB_PASSWORD:
                raise RuntimeError(
                    "Missing required AlgoLab credentials for BROKER_PROVIDER=algolab"
                )
            if not self.ALGOLAB_DRY_RUN and not self.CONFIRM_LIVE_TRADING:
                raise RuntimeError(
                    "CONFIRM_LIVE_TRADING=true is required when ALGOLAB_DRY_RUN=false"
                )
            return

    def validate_data_provider_config(self) -> None:
        if self.DATA_PROVIDER == "official":
            missing = []
            if not self.OFFICIAL_API_BASE_URL:
                missing.append("OFFICIAL_API_BASE_URL")
            if not self.OFFICIAL_API_KEY:
                missing.append("OFFICIAL_API_KEY")
            if not self.OFFICIAL_USERNAME:
                missing.append("OFFICIAL_USERNAME")
            if not self.OFFICIAL_PASSWORD:
                missing.append("OFFICIAL_PASSWORD")
            if missing:
                raise RuntimeError(
                    f"Missing required settings for DATA_PROVIDER=official: {', '.join(missing)}"
                )

    def collect_preflight_errors(self) -> list[str]:
        """Return logical configuration errors that should block runtime startup.

        These checks catch dangerous or inconsistent env/default combinations
        before scanners, risk manager, or Streamlit UI consume them.
        """
        errors: list[str] = []
        max_score = 100.0

        # --- Capital / risk limits ---
        if self.INITIAL_CAPITAL <= 0:
            errors.append("INITIAL_CAPITAL must be > 0")
        if not (0 < float(self.MAX_POSITION_CAP_PCT) <= 25.0):
            errors.append(
                "MAX_POSITION_CAP_PCT must be in (0, 25]; values above 25% of capital are unsafe"
            )
        if not (0 < float(self.MAX_TOTAL_RISK_PCT) <= 10.0):
            errors.append("MAX_TOTAL_RISK_PCT must be in (0, 10]")
        if float(self.MAX_TOTAL_RISK_PCT) > float(self.MAX_POSITION_CAP_PCT):
            errors.append(
                "MAX_TOTAL_RISK_PCT cannot exceed MAX_POSITION_CAP_PCT "
                f"({self.MAX_TOTAL_RISK_PCT} > {self.MAX_POSITION_CAP_PCT})"
            )
        if not (0 < float(self.MAX_SECTOR_CAP_PCT) <= 100.0):
            errors.append("MAX_SECTOR_CAP_PCT must be in (0, 100]")
        if not (0 < float(self.DAILY_LOSS_CAP_PCT) <= 20.0):
            errors.append("DAILY_LOSS_CAP_PCT must be in (0, 20]")
        if not (0.0 < float(self.CORRELATION_THRESHOLD) <= 1.0):
            errors.append("CORRELATION_THRESHOLD must be in (0, 1]")
        if not (0.0 < float(self.CORRELATION_MIN_SCALE) <= 1.0):
            errors.append("CORRELATION_MIN_SCALE must be in (0, 1]")
        if not (0.0 < float(self.KELLY_FRACTION_SCALE) <= 1.0):
            errors.append("KELLY_FRACTION_SCALE must be in (0, 1]")
        if not (0.0 <= float(self.MIN_SIGNAL_PROBABILITY) <= 1.0):
            errors.append("MIN_SIGNAL_PROBABILITY must be in [0, 1]")

        # --- Signal score thresholds (bounded by engine max |score|=100) ---
        strong_buy = float(self.STRONG_BUY_THRESHOLD)
        weak_buy = float(self.WEAK_BUY_THRESHOLD)
        weak_sell = float(self.WEAK_SELL_THRESHOLD)
        sell = float(self.SELL_THRESHOLD)
        strong_sell = float(self.STRONG_SELL_THRESHOLD)
        for name, value in (
            ("STRONG_BUY_THRESHOLD", strong_buy),
            ("WEAK_BUY_THRESHOLD", weak_buy),
            ("WEAK_SELL_THRESHOLD", weak_sell),
            ("SELL_THRESHOLD", sell),
            ("STRONG_SELL_THRESHOLD", strong_sell),
        ):
            if abs(value) > max_score:
                errors.append(f"{name} cannot exceed max score bound ±{max_score:g}")
        if not (strong_buy > weak_buy > 0):
            errors.append(
                "Buy thresholds must satisfy STRONG_BUY_THRESHOLD > WEAK_BUY_THRESHOLD > 0"
            )
        if not (strong_sell < sell < weak_sell < 0):
            errors.append(
                "Sell thresholds must satisfy STRONG_SELL_THRESHOLD < SELL_THRESHOLD < "
                "WEAK_SELL_THRESHOLD < 0"
            )
        if weak_buy <= weak_sell:
            errors.append("WEAK_BUY_THRESHOLD must be greater than WEAK_SELL_THRESHOLD")

        # --- Indicator period sanity ---
        if int(self.SMA_FAST) >= int(self.SMA_SLOW):
            errors.append("SMA_FAST must be < SMA_SLOW")
        if int(self.EMA_FAST) >= int(self.EMA_SLOW):
            errors.append("EMA_FAST must be < EMA_SLOW")
        if int(self.RSI_OVERSOLD) >= int(self.RSI_OVERBOUGHT):
            errors.append("RSI_OVERSOLD must be < RSI_OVERBOUGHT")
        if not (0 < int(self.ADX_THRESHOLD) <= 100):
            errors.append("ADX_THRESHOLD must be in (0, 100]")

        # --- Timeout / retry budgets vs Streamlit absolute budget ---
        streamlit_timeout = int(self.STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS)
        if streamlit_timeout < 1:
            errors.append("STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS must be >= 1")
        if int(self.SCAN_TIMEOUT_SECONDS) < 1:
            errors.append("SCAN_TIMEOUT_SECONDS must be >= 1")
        if int(self.PROVIDER_BATCH_TIMEOUT_SECONDS) < 1:
            errors.append("PROVIDER_BATCH_TIMEOUT_SECONDS must be >= 1")
        if int(self.PROVIDER_SINGLE_TIMEOUT_SECONDS) < 1:
            errors.append("PROVIDER_SINGLE_TIMEOUT_SECONDS must be >= 1")
        if float(self.OFFICIAL_TIMEOUT) <= 0:
            errors.append("OFFICIAL_TIMEOUT must be > 0")
        if int(self.PROVIDER_BATCH_TIMEOUT_SECONDS) >= streamlit_timeout:
            errors.append(
                "PROVIDER_BATCH_TIMEOUT_SECONDS must be < STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS "
                f"({self.PROVIDER_BATCH_TIMEOUT_SECONDS} >= {streamlit_timeout})"
            )
        if int(self.PROVIDER_SINGLE_TIMEOUT_SECONDS) >= streamlit_timeout:
            errors.append(
                "PROVIDER_SINGLE_TIMEOUT_SECONDS must be < STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS "
                f"({self.PROVIDER_SINGLE_TIMEOUT_SECONDS} >= {streamlit_timeout})"
            )
        if float(self.OFFICIAL_TIMEOUT) >= streamlit_timeout:
            errors.append(
                "OFFICIAL_TIMEOUT must be < STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS "
                f"({self.OFFICIAL_TIMEOUT} >= {streamlit_timeout})"
            )
        if int(self.SCAN_TIMEOUT_SECONDS) > streamlit_timeout:
            errors.append(
                "SCAN_TIMEOUT_SECONDS must be <= STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS "
                f"({self.SCAN_TIMEOUT_SECONDS} > {streamlit_timeout})"
            )
        if int(self.OFFICIAL_MAX_RETRIES) < 1 or int(self.OFFICIAL_MAX_RETRIES) > 5:
            errors.append("OFFICIAL_MAX_RETRIES must be in [1, 5]")
        if int(self.YFINANCE_MAX_RETRIES) < 1 or int(self.YFINANCE_MAX_RETRIES) > 5:
            errors.append("YFINANCE_MAX_RETRIES must be in [1, 5]")
        if float(self.OFFICIAL_MAX_RETRY_SLEEP_SECONDS) < 0:
            errors.append("OFFICIAL_MAX_RETRY_SLEEP_SECONDS must be >= 0")
        if float(self.YFINANCE_MAX_RETRY_SLEEP_SECONDS) < 0:
            errors.append("YFINANCE_MAX_RETRY_SLEEP_SECONDS must be >= 0")

        # --- Scheduler / port ---
        if self.SCAN_INTERVAL_MINUTES < 1:
            errors.append("SCAN_INTERVAL_MINUTES must be >= 1")
        if self.FLASK_PORT < 1 or self.FLASK_PORT > 65535:
            errors.append("FLASK_PORT must be between 1 and 65535")
        if int(self.MARKET_OPEN_HOUR) >= int(self.MARKET_CLOSE_HOUR):
            errors.append("MARKET_OPEN_HOUR must be < MARKET_CLOSE_HOUR")

        return errors

    def validate_all(self) -> list[str]:
        """Collect broker/provider + preflight configuration errors."""
        errors: list[str] = []
        for validator in (
            self.validate_broker_config,
            self.validate_data_provider_config,
        ):
            try:
                validator()
            except RuntimeError as exc:
                errors.append(str(exc))
        errors.extend(self.collect_preflight_errors())
        # Preserve stable ordering while removing duplicates.
        return list(dict.fromkeys(errors))

    def enforce_preflight_validation(self) -> None:
        """Fail closed when configuration is dangerous or inconsistent.

        Raises:
            RuntimeError: with a ``Configuration Error:`` prefix and all reasons.
        """
        errors = self.collect_preflight_errors()
        if not errors:
            return
        details = "; ".join(errors)
        message = f"Configuration Error: {details}"
        raise RuntimeError(message)

    SCAN_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: int(os.environ.get("SCAN_TIMEOUT_SECONDS", "30"))
    )
    STREAMLIT_INITIAL_SCAN_LIMIT: int = field(
        default_factory=lambda: int(os.environ.get("STREAMLIT_INITIAL_SCAN_LIMIT", "10"))
    )
    # Keep aligned with ServerSettings default so UI/worker budgets stay consistent.
    STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: int(
            os.environ.get("STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS", "180")
        )
    )


_SETTINGS_FIELD_NAMES = frozenset(Settings.__dataclass_fields__)
settings = Settings()
