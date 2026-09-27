"""Overnight strategy paper track record (scripts/research/OVERNIGHT_PREREGISTRATION.md).

Three idempotent steps, driven by ``run_if_due(now)`` from the scheduler:

- evening (from 15 min before the continuous close): pick O1-O3 from today's
  running daily bars and post the list to the operator chat, so the orders can
  go into the closing auction by hand (Midas has no public API);
- after the session: if the evening step was missed, pick from the day's data;
- morning (from 10:45): for every open night, price the entry at the official
  close of the entry day and the exits at the next session's opening auction
  and at 10:30 (close of the 10:15 15m bar), write the ledger and post a summary.

Prices are always re-read from fresh bars rather than stored, so a delayed
evening feed never becomes the recorded entry price.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings as default_settings
from bist_bot.market_calendar import bist_close_time, bist_eod_time, is_bist_holiday
from bist_bot.notifier import TR
from bist_bot.strategy import overnight as rules
from bist_bot.strategy.monthly_portfolio import pit_members

logger = get_logger(__name__, component="overnight")

LIST_LEAD = timedelta(minutes=15)
EXIT_CHECK = time(10, 45)
EXIT_BAR = time(10, 15)  # its close is the 10:30 price
GIVE_UP_AFTER = time(17, 0)
HISTORY_FIELDS = [
    "entry_date",
    "exit_date",
    "rule",
    "exit",
    "n",
    "gross",
    "net",
    "days",
    "source",
    "tickers",
]
RULE_NAMES = {"O1": "Tümü (likit 50)", "O2": "Gün içi kaybedenler", "O3": "Güçlü kapanış"}


class OvernightService:
    def __init__(
        self,
        fetcher: Any,
        notifier: Any,
        settings: Any = default_settings,
        results_dir: str | Path = "results",
    ) -> None:
        self.fetcher = fetcher
        self.notifier = notifier
        self.settings = settings
        self.results_dir = Path(results_dir)
        self.state_path = self.results_dir / "overnight_state.json"
        self.history_path = self.results_dir / "overnight_history.csv"

    def run_if_due(self, now: datetime) -> None:
        if not getattr(self.settings, "OVERNIGHT_ENABLED", False):
            return
        now = now.astimezone(TR)
        today = now.date()
        if is_bist_holiday(today):
            return
        state = self._load_state()
        nights: dict[str, Any] = state.setdefault("nights", {})
        if now.time() >= EXIT_CHECK:
            self._close_nights(nights, now)
        key = today.isoformat()
        close_at = datetime.combine(today, bist_close_time(today), tzinfo=TR)
        if key not in nights and now >= close_at - LIST_LEAD:
            eod_at = datetime.combine(today, bist_eod_time(today), tzinfo=TR)
            source = "eod" if now >= eod_at else "list"
            picks = self._pick(today)
            if picks:
                nights[key] = {"picks": picks, "source": source}
                self._notify(self._format_list(today, picks, source))
        self._save_state(state)

    # ------------------------------------------------------------------
    def _pick(self, today: date) -> dict[str, list[str]] | None:
        members = pit_members(today)
        daily = {t: df for t in members if (df := self._daily(t)) is not None}
        day = pd.Timestamp(today)
        universe = rules.liquid_universe(daily, members, day - pd.Timedelta(days=1))
        rows = {t: daily[t].loc[day] for t in universe if day in daily[t].index}
        if len(rows) < 20:
            logger.warning("overnight_pick_skipped", reason="too_few_bars", count=len(rows))
            return None
        today_bars = pd.DataFrame(rows).T[["open", "high", "low", "close"]].astype(float)
        return rules.pick(today_bars)

    def _close_nights(self, nights: dict[str, Any], now: datetime) -> None:
        for key in sorted(nights):
            entry_day = date.fromisoformat(key)
            if entry_day >= now.date():
                continue
            night = nights[key]
            tickers = sorted({t for names in night["picks"].values() for t in names})
            daily = {t: df for t in tickers if (df := self._daily(t, force=True)) is not None}
            later = sorted({d for df in daily.values() for d in df.index if d.date() > entry_day})
            if not later:
                continue  # next session not in the data yet
            exit_day = later[0]
            entry = self._prices(daily, pd.Timestamp(entry_day), "close")
            opens = self._prices(daily, exit_day, "open")
            at_1030 = self._price_1030(tickers, exit_day.date())
            if not opens:
                if now.time() >= GIVE_UP_AFTER:
                    del nights[key]
                    logger.warning(
                        "overnight_night_dropped", entry_date=key, reason="no_open_prices"
                    )
                    self._notify(
                        f"⚠️ Gece stratejisi: {key} gecesi için açılış fiyatı alınamadı, kayda geçmedi."
                    )
                continue
            rows = []
            for rule in rules.RULES:
                names = night["picks"].get(rule, [])
                leg_entry = {t: entry[t] for t in names if t in entry}
                for label, prices in (("open", opens), ("10:30", at_1030)):
                    gross, n = rules.basket_return(leg_entry, prices)
                    if not n:
                        continue
                    rows.append(
                        {
                            "entry_date": key,
                            "exit_date": exit_day.date().isoformat(),
                            "rule": rule,
                            "exit": label,
                            "n": n,
                            "gross": round(gross, 6),
                            "net": round(gross - 2 * rules.COST_PER_SIDE, 6),
                            "days": (exit_day.date() - entry_day).days,
                            "source": night.get("source", ""),
                            "tickers": " ".join(t.removesuffix(".IS") for t in names)
                            if rule != "O1"
                            else f"{len(names)} hisse",
                        }
                    )
            self._append(rows)
            del nights[key]
            self._notify(self._format_result(entry_day, exit_day.date(), rows))
            logger.info("overnight_night_closed", entry_date=key, exit_date=str(exit_day.date()))

    def _daily(self, ticker: str, force: bool = False) -> pd.DataFrame | None:
        df = self.fetcher.fetch_single(ticker, period="6mo", interval="1d", force=force)
        if df is None or df.empty or "close" not in df.columns:
            return None
        df = df.copy()
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df[~df.index.duplicated(keep="last")]

    @staticmethod
    def _prices(daily: dict[str, pd.DataFrame], day: pd.Timestamp, column: str) -> dict[str, float]:
        return {
            t: float(df.loc[day, column])
            for t, df in daily.items()
            if day in df.index and pd.notna(df.loc[day, column])
        }

    def _price_1030(self, tickers: list[str], day: date) -> dict[str, float]:
        bar_utc = (
            pd.Timestamp(datetime.combine(day, EXIT_BAR), tz=TR).tz_convert("UTC").tz_localize(None)
        )
        out = {}
        for t in tickers:
            df = self.fetcher.fetch_single(t, period="5d", interval="15m", force=True)
            if df is None or df.empty:
                continue
            idx = pd.to_datetime(df.index)
            if idx.tz is not None:
                idx = idx.tz_convert("UTC").tz_localize(None)
            hit = df["close"].to_numpy()[idx == bar_utc]
            if len(hit):
                out[t] = float(hit[0])
        return out

    # ------------------------------------------------------------------
    def _append(self, rows: list[dict[str, Any]]) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        write_header = not self.history_path.exists()
        with self.history_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerows(rows)

    def _cumulative(self) -> dict[tuple[str, str], float]:
        if not self.history_path.exists():
            return {}
        with self.history_path.open(encoding="utf-8", newline="") as handle:
            hist = pd.DataFrame(csv.DictReader(handle))
        if hist.empty:
            return {}
        hist["net"] = hist["net"].astype(float)
        return {k: float((1 + g).prod() - 1) for k, g in hist.groupby(["rule", "exit"])["net"]}

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self, state: dict[str, Any]) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    def _notify(self, text: str) -> None:
        try:
            self.notifier.send_message(text)
        except Exception as exc:
            logger.error("overnight_notify_failed", error_type=type(exc).__name__)

    @staticmethod
    def _format_list(day: date, picks: dict[str, list[str]], source: str) -> str:
        late = " (geç — kapanış sonrası veriyle)" if source == "eod" else ""
        lines = [f"🌙 <b>Gece listesi (paper)</b> — {day.strftime('%d.%m.%Y')}{late}"]
        for rule in ("O3", "O2"):
            names = ", ".join(t.removesuffix(".IS") for t in picks.get(rule, []))
            lines.append(f"{rule} {RULE_NAMES[rule]}: {names}")
        lines.append(f"O1 {RULE_NAMES['O1']}: {len(picks.get('O1', []))} hisse")
        lines.append(
            "Kapanış seansında al, yarın açılış seansında sat. ⚠️ Paper test, yatırım tavsiyesi değildir."
        )
        return "\n".join(lines)

    def _format_result(self, entry_day: date, exit_day: date, rows: list[dict[str, Any]]) -> str:
        cum = self._cumulative()
        by = {(r["rule"], r["exit"]): r for r in rows}
        lines = [
            f"☀️ <b>Gece sonucu (paper)</b> — {entry_day.strftime('%d.%m')} → {exit_day.strftime('%d.%m')}"
        ]

        def pct(row: dict[str, Any] | None) -> str:
            return f"%{row['net'] * 100:+.2f}" if row else "veri yok"

        for rule in rules.RULES:
            lines.append(
                f"{rule}: açılış {pct(by.get((rule, 'open')))} · 10:30 {pct(by.get((rule, '10:30')))} "
                f"(başlangıçtan beri açılış %{cum.get((rule, 'open'), 0.0) * 100:+.1f})"
            )
        lines.append("Net = yön başına %0.05 kayma düşülmüş. Fonla kıyas aylık raporda.")
        return "\n".join(lines)


__all__ = ["OvernightService"]
