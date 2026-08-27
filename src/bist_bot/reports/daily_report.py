"""Daily report generator computing canonical statistics from DB signals and scan logs."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bist_bot.config.settings import settings
from bist_bot.db.repositories.portfolio_repository import PortfolioRepository
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.reports.performance import format_performance_section
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import SignalCategory, SignalType, categorize

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

_OPEN_POSITIONS_PATH = Path("results") / "signal_outcome_open.json"
_LIQUIDITY_RE = re.compile(r"Likidite:\s*TL([\d.,]+)")
_DECAY_WARNING_FROM = (15, 30)  # 15:30 TR — intraday score-decay window opens


def _load_open_positions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load SignalOutcomeTracker's open-position JSON (best-effort, [] on error)."""
    p = path or _OPEN_POSITIONS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _parse_liquidity_tl(reasons: Any) -> float | None:
    """Extract ADTV (TL) from engine_meta's 'Likidite: TL{X} ort. islem degeri' reason."""
    for reason in reasons or []:
        match = _LIQUIDITY_RE.search(str(reason))
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                return None
    return None


_MACRO_GATE_MARKER = "Makro rejim BEAR"
_CONFLUENCE_GATE_MARKER = "MTF confluence zayıf"


def _detect_gate_tag(reasons: Any, score: float, buy_threshold: float) -> str | None:
    """Gate-demotion tag for RADAR signals whose score is at/above the AL threshold.

    ``categorize()`` promotes buy-family signals to AL only when the score clears
    the threshold; the engine can also demote buy-family candidates back to RADAR
    while preserving the score (confluence soft-fail on a neutral higher-timeframe
    bias, or the macro BEAR gate). Such rows are a distinct statistical population
    from organic RADAR (0 < score < threshold) and must be labelled in the report.
    """
    if score < buy_threshold:
        return None
    reason_list = [str(r) for r in (reasons or [])]
    if any(_MACRO_GATE_MARKER in r for r in reason_list):
        return "[Macro Bear]"
    if any(_CONFLUENCE_GATE_MARKER in r for r in reason_list):
        return "[HTF Neutral]"
    return "[Gate]"


def _format_liquidity(value: float | None, min_threshold: float) -> str:
    """Render the rollup Liq cell: '₺X.XM' plus ⚠️ when below the gate."""
    if value is None or value <= 0:
        return "-"
    display = f"₺{value / 1e6:.1f}M"
    if value < min_threshold:
        display += " ⚠️"
    return display


def _holding_minutes(entry_raw: Any, now: datetime) -> int:
    try:
        entry = _parse_row_datetime(entry_raw)
        return max(0, int((now - entry).total_seconds() // 60))
    except (TypeError, ValueError):
        return 0


def _format_holding(minutes: int) -> str:
    if minutes >= 60:
        return f"{minutes // 60}s {minutes % 60}dk"
    return f"{minutes}dk"


def _decay_warning(score: float, buy_threshold: float, now_local: datetime) -> str:
    """Faz 3 P3 (F3.4): entry score fell below the AL threshold late in session."""
    after_time = (now_local.hour, now_local.minute) >= _DECAY_WARNING_FROM
    if score < buy_threshold and after_time:
        return "⚠️ skor eşiğin altında (T+1 riski)"
    return ""


def _parse_row_datetime(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str):
        # Handle ISO strings like 2026-08-20T11:51:00 or 2026-08-20T11:51:00+00:00
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def generate_daily_report(
    day: date | None = None,
    repo: SignalsRepository | None = None,
    params: StrategyParams | None = None,
    save_to_disk: bool = True,
    *,
    open_positions: list[dict[str, Any]] | None = None,
    prices: dict[str, float] | None = None,
    now: datetime | None = None,
    portfolio_repo: PortfolioRepository | None = None,
    benchmark_return_pct: float | None = None,
) -> str:
    """Generate a markdown daily report for `day` (default today in Europe/Istanbul).

    Faz 3 P3: ``open_positions`` (default: SignalOutcomeTracker's
    results/signal_outcome_open.json) renders section 7 with holding time,
    MFE/MAE, unrealized PnL (when ``prices`` supplies a last price) and the
    15:30+ score-decay warning. ``now`` is injectable for deterministic tests.

    Sprint 1: when ``portfolio_repo`` is given, section 8 renders paper-trade
    performance metrics (Wilson CI, expectancy, score bands). RADAR listing in
    section 4 is capped by the ``RADAR_REPORT_TOP_N`` budget (gate-demoted
    first, then tier A, then tier B).
    """
    target_day = day or datetime.now(ISTANBUL_TZ).date()
    effective_now = now or datetime.now(ISTANBUL_TZ)
    signals_repo = repo or SignalsRepository()
    strategy_params = params or (
        StrategyParams.conservative()
        if getattr(settings, "STRATEGY_PROFILE", "default") == "conservative"
        else StrategyParams()
    )
    buy_threshold = strategy_params.buy_threshold

    signals = signals_repo.get_signals_for_day(target_day, tz=ISTANBUL_TZ)
    scan_logs = signals_repo.get_scan_logs_for_day(target_day, tz=ISTANBUL_TZ)

    # Classify each signal row
    categorized_signals: list[dict[str, Any]] = []
    category_counts: dict[SignalCategory, int] = defaultdict(int)

    for row in signals:
        try:
            st = SignalType.from_value(row["signal_type"])
        except ValueError:
            st = SignalType.HOLD
        score = float(row.get("score", 0.0))
        cat = categorize(st, score, buy_threshold)
        category_counts[cat] += 1
        enriched = dict(row)
        enriched["category"] = cat
        enriched["parsed_st"] = st
        enriched["score_float"] = score
        enriched["gate_tag"] = _detect_gate_tag(row.get("reasons"), score, buy_threshold)
        categorized_signals.append(enriched)

    al_signals = [s for s in categorized_signals if s["category"] is SignalCategory.AL]
    radar_signals = [s for s in categorized_signals if s["category"] is SignalCategory.RADAR]
    sat_signals = [s for s in categorized_signals if s["category"] is SignalCategory.SAT]
    hold_signals = [s for s in categorized_signals if s["category"] is SignalCategory.HOLD]
    # Gate-demotion split: a RADAR row with score >= AL threshold can only arise
    # when a risk gate demoted a buy-family candidate while preserving the score;
    # organic RADAR lives strictly below the threshold. Separate populations.
    radar_demoted = [s for s in radar_signals if s["score_float"] >= buy_threshold]
    radar_organic = [s for s in radar_signals if s["score_float"] < buy_threshold]

    # Radar tiers (organic only): A (+20 to threshold), B (+15 to 19.9), C (<15)
    radar_tier_a = [s for s in radar_organic if s["score_float"] >= 20.0]
    radar_tier_b = [s for s in radar_organic if 15.0 <= s["score_float"] < 20.0]
    radar_tier_c = [s for s in radar_organic if s["score_float"] < 15.0]

    # Sprint 1: daily RADAR listing budget (gate-demoted → tier A → tier B).
    radar_budget = max(0, int(getattr(settings, "RADAR_REPORT_TOP_N", 50)))
    radar_demoted_limit = min(len(radar_demoted), radar_budget)
    radar_tier_a_limit = min(len(radar_tier_a), radar_budget - radar_demoted_limit)
    radar_tier_b_limit = min(
        len(radar_tier_b), radar_budget - radar_demoted_limit - radar_tier_a_limit
    )

    # Session buckets (15-min or hourly depending on timestamps)
    session_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "AL": 0, "RADAR": 0, "SAT": 0, "HOLD": 0, "tickers": []}
    )
    for s in categorized_signals:
        dt_local = _parse_row_datetime(s.get("timestamp")).astimezone(ISTANBUL_TZ)
        time_str = dt_local.strftime("%H:%M")
        b = session_buckets[time_str]
        b["total"] += 1
        b[s["category"].value] += 1
        if s["category"] is SignalCategory.AL:
            b["tickers"].append(s["ticker"].replace(".IS", ""))

    # Intraday transitions per ticker
    ticker_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in categorized_signals:
        ticker = s["ticker"].replace(".IS", "")
        dt_local = _parse_row_datetime(s.get("timestamp")).astimezone(ISTANBUL_TZ)
        ticker_history[ticker].append(
            {
                "time": dt_local.strftime("%H:%M"),
                "category": s["category"],
                "score": s["score_float"],
                "gate_tag": s.get("gate_tag"),
            }
        )

    transitions: list[str] = []
    demotion_seen = False
    for ticker, hist in sorted(ticker_history.items()):
        categories = [h["category"].value for h in hist]
        if len(set(categories)) > 1:
            parts: list[str] = []
            for h in hist:
                label = h["category"].value
                if h["category"] is SignalCategory.RADAR and h.get("gate_tag"):
                    label = f"RADARe {h['gate_tag']}"
                    demotion_seen = True
                parts.append(f"{label} ({h['time']}, {h['score']:+.1f})")
            transitions.append(f"- **{ticker}**: {' -> '.join(parts)}")

    # Build markdown report
    scan_count = len(scan_logs)
    total_scanned_sum = sum(int(sl.get("total_scanned", 0)) for sl in scan_logs)

    score_al_min = min((s["score_float"] for s in al_signals), default=0.0)
    score_al_max = max((s["score_float"] for s in al_signals), default=0.0)
    score_sat_min = min((s["score_float"] for s in sat_signals), default=0.0)
    score_sat_max = max((s["score_float"] for s in sat_signals), default=0.0)

    # Unique ticker counts per category ("Tekil Hisse" column): one ticker can fire
    # several signals in a day, so the table shows both raw count and distinct names.
    unique_al = len({s["ticker"] for s in al_signals})
    unique_radar_organic = len({s["ticker"] for s in radar_organic})
    unique_radar_demoted = len({s["ticker"] for s in radar_demoted})
    unique_sat = len({s["ticker"] for s in sat_signals})
    unique_hold = len({s["ticker"] for s in hold_signals})

    # RADAR range is dynamic: from weakest positive threshold to just below AL threshold
    radar_min = float(getattr(strategy_params, "weak_buy_threshold", 8.0))
    radar_max = buy_threshold - 0.1
    radar_range_str = f"+{radar_min:.1f} ile +{radar_max:.1f}"
    if radar_demoted:
        demoted_scores = [s["score_float"] for s in radar_demoted]
        demoted_range_str = f"{min(demoted_scores):+.1f} ile {max(demoted_scores):+.1f}"
    else:
        demoted_range_str = "-"

    lines: list[str] = [
        f"# BIST Bot Günlük Sinyal ve Tarama Raporu — {target_day.isoformat()}",
        "",
        f"**Rapor Tarihi:** {target_day.strftime('%d.%m.%Y')} (Europe/Istanbul)  ",
        f"**Kullanılan Strateji Eşiği:** AL ≥ {buy_threshold:.1f} (Profil: `{getattr(settings, 'STRATEGY_PROFILE', 'default')}`)  ",
        f"**Toplam Tarama Sayısı:** {scan_count}  ",
        f"**Toplam Taranan Hisse (kümülatif):** {total_scanned_sum}  ",
        f"**Üretilen Toplam Sinyal:** {len(categorized_signals)}  ",
        "",
        "## 1. Genel Dağılım ve Özet",
        "",
        "| Kategori | Sinyal Sayısı | Tekil Hisse | Oran | Skor Aralığı |",
        "|---|---|---|---|---|",
        f"| **AL (Aksiyon Alınabilir)** | {len(al_signals)} | {unique_al} | %{len(al_signals) / max(len(categorized_signals), 1) * 100:.1f} | {score_al_min:+.1f} ile {score_al_max:+.1f} |",
        f"| **RADAR (Organik İzleme)** | {len(radar_organic)} | {unique_radar_organic} | %{len(radar_organic) / max(len(categorized_signals), 1) * 100:.1f} | {radar_range_str} |",
        f"| **RADAR (Gate-Demoted)** | {len(radar_demoted)} | {unique_radar_demoted} | %{len(radar_demoted) / max(len(categorized_signals), 1) * 100:.1f} | {demoted_range_str} |",
        f"| **SAT (Negatif / Baskı)** | {len(sat_signals)} | {unique_sat} | %{len(sat_signals) / max(len(categorized_signals), 1) * 100:.1f} | {score_sat_min:+.1f} ile {score_sat_max:+.1f} |",
        f"| **HOLD (Nötr)** | {len(hold_signals)} | {unique_hold} | %{len(hold_signals) / max(len(categorized_signals), 1) * 100:.1f} | 0.0 |",
        "",
        "*Kategori bazlı sınıflandırma sözleşmesi (`categorize()`): AL = alım yönü tipi **ve** skor ≥ eşik **ve** risk kapıları geçti. "
        "Confluence (HTF nötr) veya makro BEAR kapısı devreye girerse skor korunur ve sinyal RADAR'a düşer "
        "(raporda **RADAR (Gate-Demoted)** / `RADARe`); organik RADAR = 0 < skor < eşik. SAT = sat yönü, HOLD = nötr — tek sözleşme `categorize()`*",
        "",
        "## 2. Seans İçi Dağılım (Zaman Çizelgesi)",
        "",
        "| Saat (TR) | Toplam | AL | RADAR | SAT | HOLD | AL Veren Hisseler |",
        "|---|---|---|---|---|---|---|",
    ]

    for time_str in sorted(session_buckets.keys()):
        b = session_buckets[time_str]
        tickers_str = ", ".join(b["tickers"][:5])
        if len(b["tickers"]) > 5:
            tickers_str += f" (+{len(b['tickers']) - 5})"
        tickers_display = tickers_str if tickers_str else "-"
        lines.append(
            f"| {time_str} | {b['total']} | **{b['AL']}** | {b['RADAR']} | {b['SAT']} | {b['HOLD']} | {tickers_display} |"
        )

    lines.extend(
        [
            "",
            "## 3. Aksiyon Alınabilir AL Sinyalleri (Actionable)",
            "",
            "| Saat (TR) | Hisse | Sinyal Tipi | Skor | Fiyat | Güven |",
            "|---|---|---|---|---|---|",
        ]
    )

    for s in sorted(al_signals, key=lambda x: (x.get("timestamp", ""), -x["score_float"])):
        dt_local = _parse_row_datetime(s.get("timestamp")).astimezone(ISTANBUL_TZ)
        ticker = s["ticker"].replace(".IS", "")
        name = settings.TICKER_NAMES.get(s["ticker"], ticker)
        lines.append(
            f"| {dt_local.strftime('%H:%M')} | **{ticker}** ({name}) | {s['signal_type']} | **{s['score_float']:+.1f}** | ₺{float(s.get('price', 0.0)):.2f} | {s.get('confidence', '-')} |"
        )
    if not al_signals:
        lines.append("| - | Yok | - | - | - | - |")

    # Per-ticker AL rollup: Hisse | AL Tekrar | Maks Skor | İlk/Son | Son Fiyat | Stop | Hedef | R/R
    # Sorted by repeat count ↓ then max score ↓; AL Tekrar ≥2 → 🔁; R/R = (hedef-giriş)/(giriş-stop), stop/hedef eksik veya stop≥giriş → N/A
    al_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in al_signals:
        al_by_ticker[s["ticker"]].append(s)

    lines.extend(
        [
            "",
            "## 3.1. AL Rollup (Hisse Bazlı)",
            "",
            "| Hisse | AL Tekrar | Maks Skor | İlk/Son | Son Fiyat | Stop | Hedef | R/R | Liq (20g ort.) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )

    min_liquidity_tl = float(getattr(settings, "MIN_LIQUIDITY_VALUE_TL", 5_000_000.0))

    def _format_price(v: Any) -> str:
        try:
            f = float(v or 0)
            return f"₺{f:.2f}" if f > 0 else "N/A"
        except (TypeError, ValueError):
            return "N/A"

    def _compute_rr(sig: dict[str, Any]) -> str:
        """R/R = (hedef - giriş)/(giriş - stop); N/A when levels absent or stop>=giriş."""
        try:
            price = float(sig.get("price", 0) or 0)
            stop = float(sig.get("stop_loss", 0) or 0)
            target = float(sig.get("target_price", 0) or 0)
        except (TypeError, ValueError):
            return "N/A"
        if price <= 0 or stop <= 0 or target <= 0:
            return "N/A"
        if stop >= price:
            return "N/A"
        reward = target - price
        risk = price - stop
        if risk <= 0:
            return "N/A"
        return f"{reward / risk:.2f}"

    def _rollup_sort_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, float]:
        entries = item[1]
        max_score = max(e["score_float"] for e in entries)
        return (-len(entries), -max_score)

    if al_by_ticker:
        for ticker, entries in sorted(al_by_ticker.items(), key=_rollup_sort_key):
            sorted_entries = sorted(entries, key=lambda x: str(x.get("timestamp", "")))
            first_raw = sorted_entries[0].get("timestamp", "")
            last_raw = sorted_entries[-1].get("timestamp", "")
            try:
                first_str = _parse_row_datetime(first_raw).astimezone(ISTANBUL_TZ).strftime("%H:%M")
                last_str = _parse_row_datetime(last_raw).astimezone(ISTANBUL_TZ).strftime("%H:%M")
            except Exception:
                first_str = last_str = "-"
            ilk_son = f"{first_str}/{last_str}" if len(entries) > 1 else first_str
            last_price = sorted_entries[-1].get("price", 0)
            best = max(entries, key=lambda x: x["score_float"])
            rr = _compute_rr(best)
            liq_cell = _format_liquidity(_parse_liquidity_tl(best.get("reasons")), min_liquidity_tl)
            ticker_display = ticker.replace(".IS", "")
            if len(entries) >= 2:
                ticker_display += " 🔁"
            lines.append(
                f"| **{ticker_display}** | {len(entries)} | {best['score_float']:+.1f} | {ilk_son} | {_format_price(last_price)} | {_format_price(best.get('stop_loss'))} | {_format_price(best.get('target_price'))} | {rr} | {liq_cell} |"
            )
    else:
        lines.append("| - | - | - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 4. RADAR Kademeleri (Takip Havuzu)",
            "",
            f"### Gate-Demoted (skor ≥ {buy_threshold:.1f} ama kapı RADAR'a düşürdü) — Toplam: {len(radar_demoted)}",
            "",
        ]
    )
    if radar_demoted:
        top_demoted = sorted(radar_demoted, key=lambda x: -x["score_float"])[
            :radar_demoted_limit
        ]
        demoted_cells = []
        for s in top_demoted:
            tag = s.get("gate_tag") or "[Gate]"
            demoted_cells.append(f"**{s['ticker'].replace('.IS', '')}** ({s['score_float']:+.1f}) {tag}")
        if demoted_cells:
            lines.append(", ".join(demoted_cells))
        if len(radar_demoted) > radar_demoted_limit:
            hidden = len(radar_demoted) - radar_demoted_limit
            lines.append(f"*(+{hidden} gate-demoted sinyal listelenmedi)*")
        lines.append("")
        lines.append(
            "*Bu sinyaller AL eşiğini skor olarak geçti ancak confluence/makro kapısı tipi RADAR'a düşürdü; organik RADAR'dan ayrı popülasyondur.*"
        )
    else:
        lines.append("Yok")

    lines.extend(
        [
            "",
            f"### Kademe A (Yakın Takip / Eşik Sınırı: +20.0 – +{buy_threshold - 0.1:.1f}) — Toplam: {len(radar_tier_a)}",
            "",
        ]
    )
    if radar_tier_a:
        top_a = sorted(radar_tier_a, key=lambda x: -x["score_float"])[:radar_tier_a_limit]
        if top_a:
            lines.append(
                ", ".join(
                    [
                        f"**{s['ticker'].replace('.IS', '')}** ({s['score_float']:+.1f})"
                        for s in top_a
                    ]
                )
            )
        if len(radar_tier_a) > radar_tier_a_limit:
            hidden = len(radar_tier_a) - radar_tier_a_limit
            lines.append(f"*(+{hidden} Kademe A sinyali listelenmedi)*")
    else:
        lines.append("Yok")

    lines.extend(
        [
            "",
            f"### Kademe B (Orta Takip: +15.0 – +19.9) — Toplam: {len(radar_tier_b)}",
            "",
        ]
    )
    if radar_tier_b:
        top_b = sorted(radar_tier_b, key=lambda x: -x["score_float"])[:radar_tier_b_limit]
        if top_b:
            lines.append(
                ", ".join(
                    [
                        f"{s['ticker'].replace('.IS', '')} ({s['score_float']:+.1f})"
                        for s in top_b
                    ]
                )
            )
        if len(radar_tier_b) > radar_tier_b_limit:
            hidden = len(radar_tier_b) - radar_tier_b_limit
            lines.append(f"*(+{hidden} Kademe B sinyali listelenmedi)*")
    else:
        lines.append("Yok")

    lines.extend(
        [
            "",
            f"### Kademe C (Erken İzleme: +8.0 – +14.9) — Toplam: {len(radar_tier_c)}",
            "",
            f"{len(radar_tier_c)} adet hisse erken izleme bandında.",
            "",
            "## 5. Satış / Negatif Baskılı Hisseler (SAT Kategorisi)",
            "",
            "| Saat (TR) | Hisse | Sinyal Tipi | Skor | Fiyat |",
            "|---|---|---|---|---|",
        ]
    )

    for s in sorted(sat_signals, key=lambda x: x["score_float"])[:20]:
        dt_local = _parse_row_datetime(s.get("timestamp")).astimezone(ISTANBUL_TZ)
        ticker = s["ticker"].replace(".IS", "")
        lines.append(
            f"| {dt_local.strftime('%H:%M')} | **{ticker}** | {s['signal_type']} | {s['score_float']:+.1f} | ₺{float(s.get('price', 0.0)):.2f} |"
        )
    if not sat_signals:
        lines.append("| - | Yok | - | - | - |")

    lines.extend(
        [
            "",
            "## 6. Gün İçi Durum Değişiklikleri",
            "",
        ]
    )
    if transitions:
        lines.extend(transitions[:25])
        if demotion_seen:
            lines.append("")
            lines.append(
                "*`RADARe` = gate-demotion: skor AL eşiğinde/üstündeyken confluence `[HTF Neutral]` veya makro `[Macro Bear]` kapısı sinyali RADAR'a düşürdü (skor korunur).*"
            )
    else:
        lines.append("Gün içinde kategori değiştiren hisse tespit edilmedi.")

    # ── Faz 3 P3: §7 Açık Pozisyonlar (outcome tracker open JSON) ─────────
    positions = open_positions if open_positions is not None else _load_open_positions()
    last_prices = prices or {}
    lines.extend(
        [
            "",
            "## 7. Açık Pozisyonlar",
            "",
            "| Hisse | Yön | Giriş (TR) | Tutma | Son Fiyat | Stop | Hedef | MFE% | MAE% | U.PnL% | Uyarı |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    if not positions:
        lines.append("| - | - | - | - | - | - | - | - | - | - | Açık pozisyon yok |")
    else:
        for pos in positions:
            ticker = str(pos.get("ticker", "-")).replace(".IS", "")
            side = str(pos.get("side", "long"))
            entry_raw = pos.get("entry_ts")
            try:
                entry_local = (
                    _parse_row_datetime(entry_raw).astimezone(ISTANBUL_TZ).strftime("%H:%M")
                )
            except Exception:
                entry_local = "-"
            holding = _format_holding(_holding_minutes(entry_raw, effective_now))
            entry_price = float(pos.get("entry_price", 0) or 0)
            stop = float(pos.get("stop", 0) or 0)
            target = float(pos.get("target", 0) or 0)
            mfe = f"{float(pos.get('mfe_pct', 0) or 0):+.1f}"
            mae = f"{float(pos.get('mae_pct', 0) or 0):+.1f}"

            last_price = last_prices.get(str(pos.get("ticker", "")))
            if last_price is not None and entry_price > 0:
                direction_sign = -1.0 if side == "short" else 1.0
                upnl = f"{direction_sign * (last_price - entry_price) / entry_price * 100:+.2f}"
                last_display = f"₺{last_price:.2f}"
            else:
                upnl = "N/A"
                last_display = "N/A"

            warning = _decay_warning(
                float(pos.get("score", 0) or 0),
                buy_threshold,
                effective_now.astimezone(ISTANBUL_TZ),
            )

            def _fmt_level(value: float) -> str:
                return f"₺{value:.2f}" if value > 0 else "N/A"

            lines.append(
                f"| **{ticker}** | {side} | {entry_local} | {holding} | {last_display} "
                f"| {_fmt_level(stop)} | {_fmt_level(target)} | {mfe} | {mae} | {upnl} | {warning or '-'} |"
            )
        lines.append("")
        lines.append(
            "*Kaynak: `results/signal_outcome_open.json` (SignalOutcomeTracker). U.PnL yalnızca güncel fiyat verildiğinde hesaplanır; "
            "⚠️ = giriş skoru AL eşiğinin altına düştü ve saat ≥15:30 (gün içi elde tutma/T+1 riski).*"
        )

    # ── Sprint 1: §8 Performans Özeti (paper-trade metrik motoru) ──────────
    if portfolio_repo is not None:
        closed_trades = portfolio_repo.get_closed_trades()
        lines.append("")
        lines.extend(
            format_performance_section(
                closed_trades,
                benchmark_return_pct=benchmark_return_pct,
            )
        )

    lines.extend(
        [
            "",
            "---",
            f"*(Rapor bist_bot kanonik sınıflandırma motoru tarafından üretilmiştir. Parametre: buy_threshold={buy_threshold})*",
            "",
        ]
    )

    report_content = "\n".join(lines)

    if save_to_disk:
        results_dir = Path("results")
        results_dir.mkdir(parents=True, exist_ok=True)
        out_path = results_dir / f"daily_report_{target_day.isoformat()}.md"
        out_path.write_text(report_content, encoding="utf-8")

    return report_content
