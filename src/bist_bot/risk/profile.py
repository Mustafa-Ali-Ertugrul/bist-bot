"""Risk profile loader – reads per-environment YAML/JSON risk parameter files.

Usage:
    loader = RiskProfileLoader()          # uses default_risk_profile.yaml
    profile = loader.load()
    risk_mgr = RiskManager(
        capital=10_000,
        max_risk_pct=profile.max_risk_pct,
        max_daily_loss_pct=profile.max_daily_loss_pct,
    )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from bist_bot.app_logging import get_logger

logger = get_logger(__name__, component="risk_profile")

# Default file ships inside the package next to this module
_DEFAULT_PROFILE_PATH = Path(__file__).parent / "default_risk_profile.yaml"


class RiskProfile(BaseModel):
    """Validated, immutable risk parameter set."""

    # Position sizing
    max_risk_pct: float = Field(
        default=2.0, ge=0.0, le=100.0, description="Max capital risked per trade (%)"
    )
    max_position_cap_pct: float = Field(
        default=5.0, ge=0.0, le=100.0, description="Max single position as % of capital"
    )
    max_sector_cap_pct: float = Field(
        default=20.0, ge=0.0, le=100.0, description="Max exposure per sector (%)"
    )

    # Stop-loss & targets
    default_stop_loss_pct: float = Field(
        default=3.0, ge=0.0, description="Default stop-loss distance (%)"
    )
    default_target_ratio: float = Field(
        default=2.0, ge=0.0, description="Default risk-reward ratio (target/stop)"
    )
    atr_stop_multiplier: float = Field(
        default=2.0, ge=0.0, description="ATR multiplier for volatility stop"
    )

    # Circuit-breaker
    max_daily_loss_pct: float = Field(
        default=3.0, ge=0.0, le=100.0, description="Kill-switch: daily max loss (%)"
    )
    max_consecutive_losses: int = Field(
        default=3, ge=1, description="Kill-switch: consecutive loss count"
    )

    # Slippage / costs
    slippage_pct: float = Field(default=0.1, ge=0.0, description="Expected slippage per trade (%)")
    commission_pct: float = Field(
        default=0.1, ge=0.0, description="Brokerage commission per trade (%)"
    )

    # BSMV (Turkish financial transaction tax)
    bsmv_pct: float = Field(default=0.1, ge=0.0, description="BSMV tax on gains (%)")


class RiskProfileLoader:
    """Load and validate a risk profile from YAML or JSON.

    The loader searches for the profile file in the following order:
    1. Path supplied explicitly to ``load(path=…)``
    2. Path in the ``RISK_PROFILE_PATH`` environment variable
    3. The package-bundled ``default_risk_profile.yaml``
    """

    def __init__(self, default_path: Path | str | None = None) -> None:
        self._default_path = Path(default_path) if default_path else _DEFAULT_PROFILE_PATH

    def load(self, path: Path | str | None = None) -> RiskProfile:
        """Load and validate a risk profile from disk.

        Args:
            path: Optional override path to a YAML or JSON file.

        Returns:
            Validated ``RiskProfile`` instance.
        """
        import os

        env_path = os.environ.get("RISK_PROFILE_PATH")

        if path:
            target = Path(path)
        elif env_path:
            target = Path(env_path)
        else:
            target = self._default_path

        if not target.exists():
            logger.warning(
                "risk_profile_not_found",
                path=str(target),
                fallback="using_defaults",
            )
            return RiskProfile()

        raw = self._read_file(target)
        profile = RiskProfile(**raw)
        logger.info(
            "risk_profile_loaded",
            path=str(target),
            max_risk_pct=profile.max_risk_pct,
        )
        return profile

    @staticmethod
    def _read_file(path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            import yaml

            return yaml.safe_load(text) or {}
        if suffix == ".json":
            return json.loads(text)
        raise ValueError(f"Unsupported risk profile format: {suffix!r}. Use .yaml or .json")
