"""Membership subscription domain: plans, trial, and access decisions.

Single source of truth for "may this user see premium data":
``users.plan`` + ``users.plan_expires_at``. The ``role`` column stays purely
RBAC and is never mutated by billing flows. ``role == "admin"`` bypasses the
gate. All expiry comparisons use UTC via :func:`utcnow` (a thin clock
abstraction so tests can freeze time without touching production).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

PLAN_TRIAL = "trial"
PLAN_PRO = "pro"
PLAN_PRO_PLUS = "pro_plus"

VALID_PLANS = frozenset({PLAN_TRIAL, PLAN_PRO, PLAN_PRO_PLUS})
PAID_PLANS = frozenset({PLAN_PRO, PLAN_PRO_PLUS})


def utcnow() -> datetime:
    """Current UTC time (naive/aware-safe central clock for expiry logic)."""
    return datetime.now(UTC)


def _as_utc(value: Any) -> datetime | None:
    """Coerce DB datetime values (datetime objects or ISO strings) to UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def normalize_plan(plan: Any) -> str:
    text = str(plan or "").strip().lower()
    if text in ("pro+", "proplus", "pro_plus"):
        return PLAN_PRO_PLUS
    if text == PLAN_PRO:
        return PLAN_PRO
    return PLAN_TRIAL


def is_subscription_active(user: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """Authoritative access decision. Admin role always passes."""
    if not user:
        return False
    if str(user.get("role") or "").lower() == "admin":
        return True
    expires_at = _as_utc(user.get("plan_expires_at"))
    if expires_at is None:
        return False
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current < expires_at


def subscription_status(user: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """Public subscription snapshot for /api/me/subscription and the header badge."""
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    plan = normalize_plan((user or {}).get("plan"))
    expires_at = _as_utc((user or {}).get("plan_expires_at"))
    remaining_seconds = 0
    if expires_at is not None:
        remaining_seconds = max(0, int((expires_at - current).total_seconds()))
    active = is_subscription_active(user, now=current)
    return {
        "status": "active" if active else "expired",
        "plan": plan,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "remaining_seconds": remaining_seconds,
        "remaining_days": remaining_seconds // 86400,
    }


def plan_price_try(plan: str, pro_price: int, pro_plus_price: int) -> int | None:
    """Backend-authoritative price lookup (integer TL). None = not purchasable."""
    normalized = normalize_plan(plan)
    if normalized == PLAN_PRO:
        return int(pro_price)
    if normalized == PLAN_PRO_PLUS:
        return int(pro_plus_price)
    return None
