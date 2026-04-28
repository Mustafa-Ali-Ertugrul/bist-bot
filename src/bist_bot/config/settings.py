"""Runtime application settings loaded from environment variables."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from bist_bot.config.subsettings import (
    DEFAULT_BIST100_WATCHLIST,
    SECTOR_MAP,
    TICKER_NAMES,
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
)


@dataclass(frozen=True)
class Settings:
    DEFAULT_BIST100_WATCHLIST: list[str] = field(
        default_factory=lambda: list(DEFAULT_BIST100_WATCHLIST)
    )
    WATCHLIST: list[str] = field(default_factory=lambda: list(DEFAULT_BIST100_WATCHLIST))
    TICKER_NAMES: dict[str, str] = field(default_factory=lambda: dict(TICKER_NAMES))
    SECTOR_MAP: dict[str, str] = field(default_factory=lambda: dict(SECTOR_MAP))

    trading: TradingSettings = field(default_factory=TradingSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    data: DataSettings = field(default_factory=DataSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
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
        if self.BROKER_PROVIDER not in {"paper", "algolab"}:
            raise RuntimeError(f"Unsupported BROKER_PROVIDER: {self.BROKER_PROVIDER}")
        if self.BROKER_PROVIDER != "algolab":
            return
        if not self.ALGOLAB_API_KEY or not self.ALGOLAB_USERNAME or not self.ALGOLAB_PASSWORD:
            raise RuntimeError("Missing required AlgoLab credentials for BROKER_PROVIDER=algolab")
        if not self.ALGOLAB_DRY_RUN and not self.CONFIRM_LIVE_TRADING:
            raise RuntimeError("CONFIRM_LIVE_TRADING=true is required when ALGOLAB_DRY_RUN=false")

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

    def validate_all(self) -> list[str]:
        errors: list[str] = []
        for validator in (
            self.validate_broker_config,
            self.validate_data_provider_config,
        ):
            try:
                validator()
            except RuntimeError as exc:
                errors.append(str(exc))
        if self.SCAN_INTERVAL_MINUTES < 1:
            errors.append("SCAN_INTERVAL_MINUTES must be >= 1")
        if self.INITIAL_CAPITAL <= 0:
            errors.append("INITIAL_CAPITAL must be > 0")
        if self.FLASK_PORT < 1 or self.FLASK_PORT > 65535:
            errors.append("FLASK_PORT must be between 1 and 65535")
        return errors


settings = Settings()
_SETTINGS_FIELD_NAMES = frozenset(Settings.__dataclass_fields__)
