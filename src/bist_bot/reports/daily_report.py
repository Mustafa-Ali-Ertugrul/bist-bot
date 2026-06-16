"""Daily performance report generator for paper/live trading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data") / "paper_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def generate_daily_report(
    account_info: dict[str, Any],
    closed_trades: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    report_date: str | None = None,
) -> dict[str, Any]:
    if report_date is None:
        report_date = datetime.now(UTC).strftime("%Y-%m-%d")

    equity = _safe_float(account_info.get("equity"), 0.0)
    yesterday_equity = _safe_float(account_info.get("yesterday_equity"), equity)

    daily_return = 0.0
    if yesterday_equity > 0:
        daily_return = (equity - yesterday_equity) / yesterday_equity

    # Win rate & profit factor from closed trades
    wins = [t for t in closed_trades if _safe_float(t.get("pnl"), 0.0) > 0]
    losses = [t for t in closed_trades if _safe_float(t.get("pnl"), 0.0) <= 0]
    win_count = len(wins)
    loss_count = len(losses)
    total_count = win_count + loss_count

    win_rate = win_count / total_count if total_count > 0 else 0.0
    gross_profit = sum(_safe_float(t.get("pnl"), 0.0) for t in wins)
    gross_loss = abs(sum(_safe_float(t.get("pnl"), 0.0) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    # Drawdown (uses peak_equity if provided, else current equity as safe default)
    peak_equity = _safe_float(account_info.get("peak_equity"), max(equity, yesterday_equity))
    max_drawdown = 0.0
    if peak_equity > 0:
        max_drawdown = (peak_equity - equity) / peak_equity

    report = {
        "date": report_date,
        "equity": equity,
        "daily_return": round(daily_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "total_trades": total_count,
        "winning_trades": win_count,
        "losing_trades": loss_count,
        "open_positions": [
            {
                "symbol": p.get("symbol", p.get("ticker", "")),
                "quantity": p.get("quantity", p.get("qty", 0)),
                "market_value": p.get("market_value", 0),
                "unrealized_pnl": p.get("unrealized_pnl", 0),
            }
            for p in open_positions
        ],
    }

    output_path = REPORTS_DIR / f"daily_{report_date}.json"
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=str)

    return report


def load_daily_report(report_date: str) -> dict[str, Any] | None:
    path = REPORTS_DIR / f"daily_{report_date}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
