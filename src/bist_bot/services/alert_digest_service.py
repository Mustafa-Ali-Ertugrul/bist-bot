"""Faz 6: build and send one evening digest per user (no intraday messages)."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.db.repositories.alert_repository import AlertRepository
from bist_bot.db.repositories.market_data_repository import MarketDataRepository
from bist_bot.db.repositories.user_portfolio_repository import UserPortfolioRepository
from bist_bot.market_calendar import is_bist_holiday
from bist_bot.notifier import TR
from bist_bot.services.screener_service import ScreenerError, ScreenerService, parse_conditions
from bist_bot.strategy.scans import SCANS_BY_CODE

logger = get_logger(__name__, component="alerts")

MAX_LINES_PER_SECTION = 5


@dataclass
class DigestResult:
    user_id: int
    message: str | None = None
    sections: dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.message is None


class AlertDigestService:
    def __init__(
        self,
        alert_repository: AlertRepository,
        market_repository: MarketDataRepository,
        user_repository: UserPortfolioRepository,
        notifier: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self.alerts = alert_repository
        self.market = market_repository
        self.users = user_repository
        self.notifier = notifier
        self.settings = settings or default_settings
        self.screener = ScreenerService(market_repository, settings)
        self._last_run_date: date | None = None

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------
    def build(self, user_id: int, as_of: date) -> DigestResult:
        result = DigestResult(user_id=user_id)
        alerts = self.alerts.list_alerts(user_id)
        if not alerts:
            return result

        snapshots = {row["ticker"]: row for row in self.market.get_snapshots(as_of)}
        instruments = {item.ticker: item for item in self.market.list_instruments()}
        watchlist = set(self.users.watchlist_tickers(user_id))
        scan_dates = self.market.list_scan_dates(limit=10)
        previous_scan = next((d for d in scan_dates if d < as_of.isoformat()), None)

        lines: list[str] = []
        title = f"🌙 <b>Günlük özet · {as_of.isoformat()}</b>"

        screen_lines: list[str] = []
        for alert in alerts:
            if alert["kind"] != "screen":
                continue
            scan_id = str(alert["target"])
            scan = SCANS_BY_CODE.get(scan_id)
            if scan is None:
                continue
            today = {str(row["ticker"]) for row in self.market.get_scan_results(scan_id, as_of)}
            yesterday = (
                {
                    str(row["ticker"])
                    for row in self.market.get_scan_results(
                        scan_id, date.fromisoformat(previous_scan)
                    )
                }
                if previous_scan
                else set()
            )
            new = today - yesterday
            if alert["only_watchlist"]:
                new &= watchlist
            for ticker in sorted(new):
                screen_lines.append(
                    self._line(ticker, instruments, f"{scan.title} taramasına girdi")
                )
            if new:
                result.sections[f"screen:{scan_id}"] = len(new)

        filter_lines: list[str] = []
        snapshot_days = [row["as_of"] for row in self.market.list_snapshot_dates(limit=10)]
        previous_day = next((d for d in snapshot_days if d < as_of.isoformat()), None)
        for saved in self.alerts.list_saved_screens(user_id):
            payload = saved.get("payload") or {}
            try:
                conditions = parse_conditions(payload.get("conditions"))
                today_rows = self.screener.query(
                    conditions=conditions,
                    sector=payload.get("sector"),
                    scan_id=payload.get("scan_id"),
                    as_of=as_of,
                    limit=200,
                )
                previous_rows = (
                    self.screener.query(
                        conditions=conditions,
                        sector=payload.get("sector"),
                        scan_id=payload.get("scan_id"),
                        as_of=date.fromisoformat(previous_day),
                        limit=200,
                    )
                    if previous_day
                    else {"rows": []}
                )
            except ScreenerError:
                continue
            before = {row["code"] for row in previous_rows.get("rows", [])}
            for row in today_rows.get("rows", []):
                if row["code"] in before:
                    continue
                ticker = f"{row['code']}.IS"
                filter_lines.append(
                    self._line(ticker, instruments, f"'{saved['name']}' filtresine girdi")
                )
            entered = [row for row in today_rows.get("rows", []) if row["code"] not in before]
            if entered:
                result.sections[f"filter:{saved['id']}"] = len(entered)

        price_lines: list[str] = []
        for alert in alerts:
            if alert["kind"] == "price":
                ticker = str(alert["target"])
                snapshot = snapshots.get(ticker)
                if snapshot is None or snapshot.get("close") is None:
                    continue
                close = float(snapshot["close"])
                threshold = float(alert["threshold"] or 0)
                fired = (alert["op"] == "above" and close >= threshold) or (
                    alert["op"] == "below" and close <= threshold
                )
                if fired:
                    price_lines.append(
                        self._line(
                            ticker,
                            instruments,
                            f"kapanış {close:.2f} TL ({'≥' if alert['op'] == 'above' else '≤'} {threshold:.2f})",
                        )
                    )
                    self.alerts.disable_alert(int(alert["id"]))
                    result.sections[f"price:{alert['id']}"] = 1
            elif alert["kind"] == "change":
                ticker = str(alert["target"])
                snapshot = snapshots.get(ticker)
                if snapshot is None or snapshot.get("change_pct") is None:
                    continue
                change = float(snapshot["change_pct"])
                threshold = abs(float(alert["threshold"] or 0))
                if abs(change) >= threshold:
                    price_lines.append(
                        self._line(ticker, instruments, f"günlük değişim {change:+.2f}%")
                    )
                    result.sections[f"change:{alert['id']}"] = 1

        for heading, section_lines in (
            ("📋 <b>Taramalar</b>", screen_lines),
            ("🧮 <b>Kayıtlı filtreler</b>", filter_lines),
            ("🎯 <b>Fiyat ve değişim</b>", price_lines),
        ):
            if not section_lines:
                continue
            lines.append(heading)
            lines.extend(section_lines[:MAX_LINES_PER_SECTION])
            if len(section_lines) > MAX_LINES_PER_SECTION:
                lines.append(
                    f"… +{len(section_lines) - MAX_LINES_PER_SECTION} hisse daha (web'de görün)"
                )

        if not lines:
            return result

        base = str(getattr(self.settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
        footer = "⚠️ Yatırım tavsiyesi değildir. Veriler gün sonu ve gecikmeli olabilir."
        if base:
            footer += f' <a href="{html.escape(base)}/ui/alerts">Alarmlarım</a>'
        message = "\n".join([title, "", *lines, "", footer])
        if len(message) > 3900:
            message = message[:3800] + "\n… (mesaj kısaltıldı)"
        result.message = message
        return result

    def _line(self, ticker: str, instruments: dict[str, Any], detail: str) -> str:
        instrument = instruments.get(ticker)
        code = instrument.code if instrument else ticker.removesuffix(".IS")
        name = html.escape(instrument.name if instrument else "")
        base = str(getattr(self.settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
        label = (
            f'<a href="{html.escape(base)}/ui/stock/{code}">{html.escape(code)}</a>'
            if base
            else html.escape(code)
        )
        suffix = f" · {name}" if name else ""
        return f"• {label}{suffix} — {html.escape(detail)}"

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def run(self, *, as_of: date | None = None, send: bool = True) -> list[DigestResult]:
        target = as_of or datetime.now(TR).date()
        results: list[DigestResult] = []
        for link in self.alerts.list_links():
            user_id = int(link["user_id"])
            if self.alerts.was_digest_sent(user_id, target):
                continue
            result = self.build(user_id, target)
            results.append(result)
            if result.empty:
                continue
            if send:
                if self.notifier is not None:
                    sent = self.notifier.send_to_chat(link["chat_id"], result.message)
                    if not sent:
                        logger.warning("digest_send_failed", user_id=user_id)
                        continue
                self.alerts.mark_digest_sent(user_id, target)
                logger.info("digest_sent", user_id=user_id, as_of=target.isoformat())
        return results

    def run_if_due(self, now: datetime) -> bool:
        if not bool(getattr(self.settings, "USER_DIGEST_ENABLED", False)):
            return False
        today = now.date()
        if self._last_run_date == today:
            return False
        if is_bist_holiday(today):
            return False
        earliest_hour = max(0, min(int(getattr(self.settings, "USER_DIGEST_HOUR_TR", 18)), 23))
        if now.hour < earliest_hour:
            return False
        if self.market.latest_market_date() != today:
            logger.info("digest_skipped_no_bars", as_of=today.isoformat())
            return False
        try:
            self.run(as_of=today, send=True)
        except Exception as exc:
            logger.error("digest_run_failed", error_type=type(exc).__name__, error=str(exc))
            return False
        self._last_run_date = today
        return True
