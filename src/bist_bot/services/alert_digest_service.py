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
    fired_alert_ids: list[int] = field(default_factory=list)

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
        self._last_inapp_date: date | None = None

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------
    def build(self, user_id: int, as_of: date, *, consume: bool = True) -> DigestResult:
        result = DigestResult(user_id=user_id)
        alerts = [a for a in self.alerts.list_alerts(user_id) if a["enabled"]]
        saved_screens = self.alerts.list_saved_screens(user_id)
        if not alerts and not saved_screens:
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
        for saved in saved_screens:
            payload = saved.get("payload") or {}
            try:
                conditions = parse_conditions(payload.get("conditions"))
                today_rows = self._filter_rows(conditions, payload, as_of)
                previous_rows = (
                    self._filter_rows(conditions, payload, date.fromisoformat(previous_day))
                    if previous_day
                    else []
                )
            except ScreenerError:
                continue
            before = {row["code"] for row in previous_rows}
            entered = [row for row in today_rows if row["code"] not in before]
            for row in entered:
                ticker = f"{row['code']}.IS"
                filter_lines.append(
                    self._line(ticker, instruments, f"'{saved['name']}' filtresine girdi")
                )
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
                    result.fired_alert_ids.append(int(alert["id"]))
                    if consume:
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

    def _filter_rows(
        self, conditions: list[dict[str, Any]], payload: dict[str, Any], as_of: date
    ) -> list[dict[str, Any]]:
        """Run one saved filter to completion (every page, not just the first)."""
        rows: list[dict[str, Any]] = []
        offset = 0
        for _ in range(50):
            page = self.screener.query(
                conditions=conditions,
                sector=payload.get("sector"),
                scan_id=payload.get("scan_id"),
                as_of=as_of,
                limit=200,
                offset=offset,
            )
            batch = list(page.get("rows", []))
            rows.extend(batch)
            offset += len(batch)
            if not batch or offset >= int(page.get("total") or 0):
                break
        return rows

    def _line(self, ticker: str, instruments: dict[str, Any], detail: str) -> str:
        instrument = instruments.get(ticker)
        code = instrument.code if instrument else ticker.removesuffix(".IS")
        name = html.escape(instrument.name if instrument else "")
        base = str(getattr(self.settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
        label = (
            f'<a href="{html.escape(base)}/ui/stock/{html.escape(code)}">{html.escape(code)}</a>'
            if base
            else html.escape(code)
        )
        suffix = f" · {name}" if name else ""
        return f"• {label}{suffix} — {html.escape(detail)}"

    # ------------------------------------------------------------------
    # In-app events (Faz P3.3)
    # ------------------------------------------------------------------
    def build_events(self, user_id: int, as_of: date) -> list[dict[str, Any]]:
        """Map one digest build into per-section in-app events (no Telegram)."""
        alerts = {int(a["id"]): a for a in self.alerts.list_alerts(user_id) if a["enabled"]}
        saved = {int(item["id"]): item for item in self.alerts.list_saved_screens(user_id)}
        result = self.build(user_id, as_of, consume=False)

        events: list[dict[str, Any]] = []
        for key, count in result.sections.items():
            scope, _, ref = key.partition(":")
            if scope == "screen":
                scan = SCANS_BY_CODE.get(ref)
                title = f"{scan.title} taramasında {count} yeni hisse" if scan else f"{ref}: {count}"
                kind = "scan"
            elif scope == "filter":
                item = saved.get(int(ref)) if ref.isdigit() else None
                name = item["name"] if item else ref
                title = f"'{name}' filtresine {count} hisse girdi"
                kind = "filter"
            else:
                alert = alerts.get(int(ref)) if ref.isdigit() else None
                if alert is not None:
                    target = str(alert["target"]).replace(".IS", "")
                    if alert["kind"] == "price":
                        title = f"{target} fiyat alarmı tetiklendi"
                    else:
                        title = f"{target} günlük değişim alarmı tetiklendi"
                else:
                    title = "Alarm tetiklendi"
                kind = "alert"
            events.append(
                {
                    "kind": kind,
                    "ref": key,
                    "title": title,
                    "message": result.message,
                }
            )
        return events

    def run_inapp(self, *, as_of: date | None = None) -> dict[str, int]:
        """Write in-app events for every user with alerts or saved screens."""
        target = as_of or datetime.now(TR).date()
        users = 0
        events = 0
        for user_id in self.alerts.list_user_ids_with_alerts():
            try:
                rows = self.build_events(int(user_id), target)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "alert_events_build_failed", user_id=user_id, error_type=type(exc).__name__
                )
                continue
            users += 1
            events += self.alerts.record_events(int(user_id), target, rows)
        logger.info("alert_events_written", users=users, events=events, as_of=target.isoformat())
        return {"users": users, "events": events}

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
            result = self.build(user_id, target, consume=False)
            results.append(result)
            if result.empty or not send:
                continue
            if self.notifier is None:
                logger.warning("digest_notifier_missing", user_id=user_id)
                continue
            try:
                sent = self.notifier.send_to_chat(link["chat_id"], result.message)
            except Exception as exc:
                logger.warning(
                    "digest_send_error", user_id=user_id, error_type=type(exc).__name__
                )
                continue
            if not sent:
                logger.warning("digest_send_failed", user_id=user_id)
                continue
            # Record the history before consuming one-shot alerts: after
            # ``disable_alert`` the event builder no longer sees them.
            self._record_events_for(user_id, target)
            for alert_id in result.fired_alert_ids:
                self.alerts.disable_alert(alert_id)
            self.alerts.mark_digest_sent(user_id, target)
            logger.info("digest_sent", user_id=user_id, as_of=target.isoformat())
        return results

    def _record_events_for(self, user_id: int, as_of: date) -> int:
        """Write the day's in-app events for one user; never fails the digest."""
        if not bool(getattr(self.settings, "IN_APP_ALERT_EVENTS_ENABLED", True)):
            return 0
        try:
            rows = self.build_events(user_id, as_of)
            return self.alerts.record_events(user_id, as_of, rows)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "alert_events_build_failed", user_id=user_id, error_type=type(exc).__name__
            )
            return 0

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

    def run_inapp_if_due(self, now: datetime) -> bool:
        """Write the day's in-app alert events after the close (no Telegram needed)."""
        if not bool(getattr(self.settings, "IN_APP_ALERT_EVENTS_ENABLED", True)):
            return False
        today = now.date()
        if self._last_inapp_date == today:
            return False
        if is_bist_holiday(today):
            return False
        earliest_hour = max(0, min(int(getattr(self.settings, "USER_DIGEST_HOUR_TR", 18)), 23))
        if now.hour < earliest_hour:
            return False
        if self.market.latest_market_date() != today:
            return False
        try:
            self.run_inapp(as_of=today)
        except Exception as exc:
            logger.error(
                "alert_events_run_failed", error_type=type(exc).__name__, error=str(exc)
            )
            return False
        self._last_inapp_date = today
        return True
