"""Faz 7: one place for what each plan may use.

Trial counts as the free tier. Admin bypasses every limit. Sales stay closed
until the external prerequisites (company, payment account, data licence) exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bist_bot.subscription import PAID_PLANS, is_subscription_active, normalize_plan


@dataclass(frozen=True)
class Entitlements:
    plan: str
    paid: bool
    screener_rows: int
    saved_screens: int
    alerts: int
    watchlists: int
    watchlist_items: int
    portfolios: int
    transactions: int
    history_days: int


def entitlements_for(user: dict[str, Any] | None, settings: Any) -> Entitlements:
    if user is None:
        return Entitlements("none", False, 0, 0, 0, 0, 0, 0, 0, 0)
    if str(user.get("role") or "").lower() == "admin":
        return Entitlements("admin", True, 200, 50, 100, 20, 500, 20, 2000, 3650)

    plan = normalize_plan(user.get("plan"))
    paid = plan in PAID_PLANS and is_subscription_active(user)
    if paid:
        return Entitlements(
            plan=plan,
            paid=True,
            screener_rows=int(getattr(settings, "PAID_SCREENER_ROWS", 200)),
            saved_screens=int(getattr(settings, "PAID_SAVED_SCREENS", 10)),
            alerts=int(getattr(settings, "PAID_ALERTS", 20)),
            watchlists=int(getattr(settings, "PAID_WATCHLISTS", 5)),
            watchlist_items=int(getattr(settings, "PAID_WATCHLIST_ITEMS", 100)),
            portfolios=int(getattr(settings, "PAID_PORTFOLIOS", 3)),
            transactions=int(getattr(settings, "PAID_TRANSACTIONS", 500)),
            history_days=int(getattr(settings, "PAID_HISTORY_DAYS", 730)),
        )
    return Entitlements(
        plan="free",
        paid=False,
        screener_rows=max(0, min(int(getattr(settings, "SCREENER_FREE_LIMIT", 5)), 5)),
        saved_screens=int(getattr(settings, "FREE_SAVED_SCREENS", 1)),
        alerts=int(getattr(settings, "FREE_ALERTS", 3)),
        watchlists=int(getattr(settings, "FREE_WATCHLISTS", 1)),
        watchlist_items=int(getattr(settings, "FREE_WATCHLIST_ITEMS", 20)),
        portfolios=int(getattr(settings, "FREE_PORTFOLIOS", 1)),
        transactions=int(getattr(settings, "FREE_TRANSACTIONS", 50)),
        history_days=int(getattr(settings, "FREE_HISTORY_DAYS", 90)),
    )


__all__ = ["Entitlements", "entitlements_for"]
