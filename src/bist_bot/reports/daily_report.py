"""Daily report generator computing canonical statistics from DB signals and scan logs."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bist_bot.config.settings import settings
from bist_bot.db.repositories.signals_repository import SignalsRepository
from bist_bot.strategy.params import StrategyParams
from bist_bot.strategy.signal_models import SignalCategory, SignalType, categorize

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


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
) -> str:
    """Generate a markdown daily report for `day` (default today in Europe/Istanbul)."""
    target_day = day or datetime.now(ISTANBUL_TZ).date()
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
        categorized_signals.append(enriched)

    al_signals = [s for s in categorized_signals if s["category"] is SignalCategory.AL]
    radar_signals = [s for s in categorized_signals if s["category"] is SignalCategory.RADAR]
    sat_signals = [s for s in categorized_signals if s["category"] is SignalCategory.SAT]
    hold_signals = [s for s in categorized_signals if s["category"] is SignalCategory.HOLD]

    # Radar tiers: A (+20 to 24.9), B (+15 to 19.9), C (+8 to 14.9)
    radar_tier_a = [s for s in radar_signals if s["score_float"] >= 20.0]
    radar_tier_b = [s for s in radar_signals if 15.0 <= s["score_float"] < 20.0]
    radar_tier_c = [s for s in radar_signals if s["score_float"] < 15.0]

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
            }
        )

    transitions: list[str] = []
    for ticker, hist in sorted(ticker_history.items()):
        categories = [h["category"].value for h in hist]
        if len(set(categories)) > 1:
            seq = " -> ".join(
                [f"{h['category'].value} ({h['time']}, {h['score']:+.1f})" for h in hist]
            )
            transitions.append(f"- **{ticker}**: {seq}")

    # Build markdown report
    scan_count = len(scan_logs)
    total_scanned_sum = sum(int(sl.get("total_scanned", 0)) for sl in scan_logs)

    score_al_min = min((s["score_float"] for s in al_signals), default=0.0)
    score_al_max = max((s["score_float"] for s in al_signals), default=0.0)
    score_sat_min = min((s["score_float"] for s in sat_signals), default=0.0)
    score_sat_max = max((s["score_float"] for s in sat_signals), default=0.0)

    # RADAR range is dynamic: from weakest positive threshold to just below AL threshold
    radar_min = float(getattr(strategy_params, "weak_buy_threshold", 8.0))
    radar_max = buy_threshold - 0.1
    radar_range_str = f"+{radar_min:.1f} ile +{radar_max:.1f}"

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
        "| Kategori | Sinyal Sayısı | Oran | Skor Aralığı |",
        "|---|---|---|---|",
        f"| **AL (Aksiyon Alınabilir)** | {len(al_signals)} | %{len(al_signals) / max(len(categorized_signals), 1) * 100:.1f} | {score_al_min:+.1f} ile {score_al_max:+.1f} |",
        f"| **RADAR (İzleme Havuzu)** | {len(radar_signals)} | %{len(radar_signals) / max(len(categorized_signals), 1) * 100:.1f} | {radar_range_str} |",
        f"| **SAT (Negatif / Baskı)** | {len(sat_signals)} | %{len(sat_signals) / max(len(categorized_signals), 1) * 100:.1f} | {score_sat_min:+.1f} ile {score_sat_max:+.1f} |",
        f"| **HOLD (Nötr)** | {len(hold_signals)} | %{len(hold_signals) / max(len(categorized_signals), 1) * 100:.1f} | 0.0 |",
        "",
        "*Kategori bazlı görünüm: AL ≥ buy_threshold, RADAR = 0 < skor < AL eşiği (pozitif izleme), SAT = sat yönü, HOLD = nötr — tek sözleşme `categorize()`*",
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
            "| Hisse | AL Tekrar | Maks Skor | İlk/Son | Son Fiyat | Stop | Hedef | R/R |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )

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
            ticker_display = ticker.replace(".IS", "")
            if len(entries) >= 2:
                ticker_display += " 🔁"
            lines.append(
                f"| **{ticker_display}** | {len(entries)} | {best['score_float']:+.1f} | {ilk_son} | {_format_price(last_price)} | {_format_price(best.get('stop_loss'))} | {_format_price(best.get('target_price'))} | {rr} |"
            )
    else:
        lines.append("| - | - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 4. RADAR Kademeleri (Takip Havuzu)",
            "",
            f"### Kademe A (Yakın Takip / Eşik Sınırı: +20.0 – +24.9) — Toplam: {len(radar_tier_a)}",
            "",
        ]
    )
    if radar_tier_a:
        top_a = sorted(radar_tier_a, key=lambda x: -x["score_float"])[:15]
        lines.append(
            ", ".join(
                [f"**{s['ticker'].replace('.IS', '')}** ({s['score_float']:+.1f})" for s in top_a]
            )
        )
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
        top_b = sorted(radar_tier_b, key=lambda x: -x["score_float"])[:15]
        lines.append(
            ", ".join(
                [f"{s['ticker'].replace('.IS', '')} ({s['score_float']:+.1f})" for s in top_b]
            )
        )
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
    else:
        lines.append("Gün içinde kategori değiştiren hisse tespit edilmedi.")

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
