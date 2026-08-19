"""Compare two walk-forward runs (H3 ON vs H3 OFF) and write the A/B report.

Consumes the CSVs produced by ``scripts/run_walk_forward_bist30.py`` and emits a
markdown report with universe aggregates, a per-ticker delta table and (when the
diagnose CSV is supplied) the chase diagnostics summary.

Usage (from repo root):
    python scripts/compare_h3_ab.py \
        --on results/wf_bist30_h3_on.csv \
        --off results/wf_bist30_h3_off.csv \
        --diagnose results/chase_diagnose_h3on.csv \
        --out results/h3_ab_report.md

The decision sentence is derived mechanically from the aggregates:
    OOS improves or stays flat -> H3 kalir
    both arms byte-identical    -> redundant (zararsiz)
    OOS degrades                -> kill-switch onerisi (kullanici onayi gerekir)
"""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ON = REPO_ROOT / "results" / "wf_bist30_h3_on.csv"
DEFAULT_OFF = REPO_ROOT / "results" / "wf_bist30_h3_off.csv"
DEFAULT_DIAGNOSE = REPO_ROOT / "results" / "chase_diagnose_h3on.csv"
DEFAULT_OUT = REPO_ROOT / "results" / "h3_ab_report.md"

#: Aggregate difference (percentage points) below which the two arms are treated
#: as "no material change".
FLAT_EPS = 0.01


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@dataclass
class Aggregate:
    label: str
    tickers_total: int
    tickers_ok: int
    median_oos: float
    mean_oos: float
    positive_share: float
    positive_count: int
    overfit_share: float
    overfit_count: int
    total_trades: int
    mean_max_dd: float
    top5: list[tuple[str, float]]
    bottom5: list[tuple[str, float]]


def aggregate(rows: list[dict[str, Any]], label: str) -> Aggregate:
    ok_rows = [row for row in rows if row.get("status") == "OK"]
    oos = [
        (row["ticker"], _to_float(row.get("oos_mean_return")))
        for row in ok_rows
        if _to_float(row.get("oos_mean_return")) is not None
    ]
    values = [value for _, value in oos]
    ranked = sorted(oos, key=lambda item: item[1], reverse=True)
    n = len(ok_rows) or 1
    positive = sum(1 for value in values if value > 0)
    overfit = sum(1 for row in ok_rows if _to_bool(row.get("has_overfitting_warning")))
    dds = [
        _to_float(row.get("oos_max_dd"))
        for row in ok_rows
        if _to_float(row.get("oos_max_dd")) is not None
    ]
    return Aggregate(
        label=label,
        tickers_total=len(rows),
        tickers_ok=len(ok_rows),
        median_oos=statistics.median(values) if values else 0.0,
        mean_oos=statistics.fmean(values) if values else 0.0,
        positive_share=100.0 * positive / n,
        positive_count=positive,
        overfit_share=100.0 * overfit / n,
        overfit_count=overfit,
        total_trades=sum(int(_to_float(row.get("total_oos_trades")) or 0) for row in ok_rows),
        mean_max_dd=statistics.fmean(dds) if dds else 0.0,
        top5=ranked[:5],
        bottom5=ranked[-5:][::-1],
    )


def diagnose_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    rows = read_rows(path)
    capped = sum(1 for row in rows if str(row.get("capped", "")).upper() == "YES")
    return {
        "logged_rows": len(rows),
        "capped_rows": capped,
        "tickers": sorted({row["ticker"] for row in rows if row.get("ticker")}),
        "h4_long_fired": max(
            (int(_to_float(row.get("h4_long_fired")) or 0) for row in rows), default=0
        ),
        "h6_neutralized": max(
            (int(_to_float(row.get("h6_confluence_neutralized")) or 0) for row in rows), default=0
        ),
    }


def decide(on: Aggregate, off: Aggregate, identical: bool) -> tuple[str, str]:
    """Return ``(verdict, sentence)`` from the locked decision rule."""
    delta_mean = on.mean_oos - off.mean_oos
    delta_median = on.median_oos - off.median_oos
    if identical:
        return (
            "redundant",
            "KARAR: H3 REDUNDANT — iki kol birebir ayni sonucu verdi; cap'liyor olsa bile "
            "trade'lere yansimiyor. Zararsiz; kaldirmak da tutmak da OOS'u degistirmez.",
        )
    if delta_mean >= -FLAT_EPS and delta_median >= -FLAT_EPS:
        return (
            "keep",
            "KARAR: H3 KALIR — H3 acikken OOS ortalama/medyan bozulmuyor "
            f"(delta mean {delta_mean:+.2f} pp, delta median {delta_median:+.2f} pp).",
        )
    return (
        "kill_switch",
        "KARAR: KILL-SWITCH ONERISI — H3 acikken OOS bozuluyor "
        f"(delta mean {delta_mean:+.2f} pp, delta median {delta_median:+.2f} pp). "
        "chase_block_enabled=False onerilir; UYGULAMA KULLANICI ONAYINA TABIDIR.",
    )


def _agg_table(on: Aggregate, off: Aggregate) -> list[str]:
    def row(name: str, a: float, b: float, fmt: str = "{:.2f}") -> str:
        delta = a - b
        return f"| {name} | {fmt.format(a)} | {fmt.format(b)} | {delta:+.2f} |"

    return [
        "| Metrik | H3 ON | H3 OFF | Delta (ON−OFF) |",
        "|---|---:|---:|---:|",
        f"| tickers OK | {on.tickers_ok}/{on.tickers_total} | "
        f"{off.tickers_ok}/{off.tickers_total} | {on.tickers_ok - off.tickers_ok:+d} |",
        row("median OOS return %", on.median_oos, off.median_oos),
        row("mean OOS return %", on.mean_oos, off.mean_oos),
        row("pozitif OOS payi %", on.positive_share, off.positive_share),
        row("overfitting payi %", on.overfit_share, off.overfit_share),
        row("ortalama OOS max DD %", on.mean_max_dd, off.mean_max_dd),
        f"| toplam OOS trade | {on.total_trades} | {off.total_trades} | "
        f"{on.total_trades - off.total_trades:+d} |",
    ]


def _per_ticker_table(
    on_rows: list[dict[str, Any]], off_rows: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    on_map = {row["ticker"]: row for row in on_rows}
    off_map = {row["ticker"]: row for row in off_rows}
    tickers = sorted(set(on_map) | set(off_map))
    lines = [
        "| Ticker | Durum | OOS ON % | OOS OFF % | Delta pp | Trades ON | Trades OFF | Delta |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    changed: list[str] = []
    for ticker in tickers:
        on_row = on_map.get(ticker, {})
        off_row = off_map.get(ticker, {})
        status = on_row.get("status", off_row.get("status", "?"))
        on_oos = _to_float(on_row.get("oos_mean_return"))
        off_oos = _to_float(off_row.get("oos_mean_return"))
        on_tr = int(_to_float(on_row.get("total_oos_trades")) or 0)
        off_tr = int(_to_float(off_row.get("total_oos_trades")) or 0)
        delta = f"{on_oos - off_oos:+.2f}" if on_oos is not None and off_oos is not None else "n/a"
        if (
            on_oos is not None and off_oos is not None and abs(on_oos - off_oos) > FLAT_EPS
        ) or on_tr != off_tr:
            changed.append(ticker)
        lines.append(
            f"| {ticker} | {status} | "
            f"{'n/a' if on_oos is None else f'{on_oos:.2f}'} | "
            f"{'n/a' if off_oos is None else f'{off_oos:.2f}'} | {delta} | "
            f"{on_tr} | {off_tr} | {on_tr - off_tr:+d} |"
        )
    return lines, changed


def build_report(
    *,
    on_rows: list[dict[str, Any]],
    off_rows: list[dict[str, Any]],
    on_path: Path,
    off_path: Path,
    diagnose: dict[str, Any] | None,
    diagnose_path: Path | None,
    period: str,
    cache_note: str,
) -> tuple[str, str]:
    on = aggregate(on_rows, "H3 ON")
    off = aggregate(off_rows, "H3 OFF")
    ticker_lines, changed = _per_ticker_table(on_rows, off_rows)
    identical = not changed
    verdict, sentence = decide(on, off, identical)

    lines: list[str] = []
    lines.append("# H3 (chase / asiri uzama cap) A/B raporu")
    lines.append("")
    lines.append(f"- Uretim zamani: {datetime.now(UTC).isoformat()}")
    lines.append(f"- Kol A (H3 ON): `{on_path}`")
    lines.append(f"- Kol B (H3 OFF): `{off_path}`")
    lines.append(
        "- Kurulum: StrategyParams.conservative(), H1 (counter_trend_multiplier) her iki "
        "kolda sabit; tek degisken chase_block_enabled."
    )
    lines.append(f"- Period: {period} | {cache_note}")
    lines.append("")
    lines.append("## 1. Universe aggregate")
    lines.append("")
    lines.extend(_agg_table(on, off))
    lines.append("")
    lines.append("- Top 5 (ON): " + ", ".join(f"{t}({v:.1f}%)" for t, v in on.top5))
    lines.append("- Bottom 5 (ON): " + ", ".join(f"{t}({v:.1f}%)" for t, v in on.bottom5))
    lines.append("- Top 5 (OFF): " + ", ".join(f"{t}({v:.1f}%)" for t, v in off.top5))
    lines.append("- Bottom 5 (OFF): " + ", ".join(f"{t}({v:.1f}%)" for t, v in off.bottom5))
    lines.append("")
    lines.append("## 2. Per-ticker delta (ON − OFF)")
    lines.append("")
    lines.extend(ticker_lines)
    lines.append("")
    if changed:
        lines.append(f"Farklilasan ticker sayisi: **{len(changed)}** → {', '.join(changed)}")
    else:
        lines.append(
            "Hicbir ticker'da fark yok: iki kol **birebir ayni** sonuc uretti "
            "(H3 cap'i OOS trade setine yansimiyor)."
        )
    lines.append("")
    sasa_on = next((r for r in on_rows if r["ticker"] == "SASA.IS"), None)
    sasa_off = next((r for r in off_rows if r["ticker"] == "SASA.IS"), None)
    if sasa_on or sasa_off:
        lines.append("### SASA.IS odak")
        lines.append("")
        lines.append(
            f"- ON : status={sasa_on.get('status') if sasa_on else 'yok'} "
            f"OOS={sasa_on.get('oos_mean_return') if sasa_on else 'n/a'} "
            f"trades={sasa_on.get('total_oos_trades') if sasa_on else 'n/a'}"
        )
        lines.append(
            f"- OFF: status={sasa_off.get('status') if sasa_off else 'yok'} "
            f"OOS={sasa_off.get('oos_mean_return') if sasa_off else 'n/a'} "
            f"trades={sasa_off.get('total_oos_trades') if sasa_off else 'n/a'}"
        )
        lines.append("")
    lines.append("## 3. Chase diagnostics (Kol A)")
    lines.append("")
    if diagnose is None:
        lines.append(
            "Diagnose CSV verilmedi veya bulunamadi — `--diagnose-chase` ile Kol A'yi "
            "tekrar kosarak bu bolum doldurulabilir."
        )
    else:
        lines.append(f"- Kaynak: `{diagnose_path}`")
        lines.append(f"- Loglanan chase_high_score satiri: {diagnose['logged_rows']}")
        lines.append(f"- Gercekten cap'lenen satir (capped=YES): {diagnose['capped_rows']}")
        lines.append(f"- Etkilenen ticker sayisi: {len(diagnose['tickers'])}")
        if diagnose["tickers"]:
            lines.append(f"- Ticker'lar: {', '.join(diagnose['tickers'])}")
    lines.append("")
    lines.append("## 4. Karar")
    lines.append("")
    lines.append(sentence)
    lines.append("")
    lines.append("## 5. Rapor kisitlari")
    lines.append("")
    lines.append(
        f"- Kapsam: {on.tickers_ok}/{on.tickers_total} ticker OK; kalanlar "
        "INSUFFICIENT_DATA (offline/ag engelli cekim)."
    )
    lines.append(f"- {cache_note}")
    lines.append(f"- Period: {period}; train/test/step = 252/63/63.")
    lines.append(
        "- Kill-switch (chase_block_enabled=False) uygulamasi bu raporun kapsaminda "
        "DEGILDIR; kullanici onayi gerekir."
    )
    lines.append("")
    return "\n".join(lines), verdict


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H3 A/B walk-forward comparison report")
    parser.add_argument("--on", type=str, default=str(DEFAULT_ON))
    parser.add_argument("--off", type=str, default=str(DEFAULT_OFF))
    parser.add_argument("--diagnose", type=str, default=str(DEFAULT_DIAGNOSE))
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    parser.add_argument("--period", type=str, default="3y")
    parser.add_argument(
        "--cache-note",
        type=str,
        default="Cache: ~/.cache/bist_bot/wf_data (offline snapshot)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    on_path = Path(args.on)
    off_path = Path(args.off)
    for path in (on_path, off_path):
        if not path.exists():
            print(f"ERROR: missing input CSV: {path}")
            return 2

    diagnose_path = Path(args.diagnose) if args.diagnose else None
    report, verdict = build_report(
        on_rows=read_rows(on_path),
        off_rows=read_rows(off_path),
        on_path=on_path,
        off_path=off_path,
        diagnose=diagnose_summary(diagnose_path),
        diagnose_path=diagnose_path,
        period=args.period,
        cache_note=args.cache_note,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"verdict: {verdict}")
    print(f"report written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
