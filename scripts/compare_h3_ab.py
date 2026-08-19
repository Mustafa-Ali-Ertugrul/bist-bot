"""H3 walk-forward A/B karşılaştırma raporu üretir.

İki walk-forward sonuç CSV'sini (H3 AÇIK / H3 KAPALI kolları,
``scripts/run_walk_forward_bist30.py`` çıktısı) ve isteğe bağlı bir chase
diagnose CSV'sini okur; universe aggregate'ları, per-ticker delta'ları,
SASA.IS odağını, diagnose özetini ve mekanik karar cümlesini içeren bir
Markdown rapor yazar.

Karar kuralı (medyan OOS delta, puan yüzdesi/pp):
  * iki kol birebir aynı      → "H3 redundant"
  * delta >  +0.10 pp         → "H3 kalır"
  * delta <  -0.10 pp         → "H3 kill-switch önerilir"
  * aksi (marjinal)           → "H3 kalır (etki marjinal)"

Bu karar yalnızca RAPOR amaçlıdır. Kill-switch (``chase_block_enabled=False``)
uygulaması her zaman açık kullanıcı onayı gerektirir.

Usage (repo root):
    python scripts/compare_h3_ab.py \
        --on results/wf_bist30_h3_on.csv \
        --off results/wf_bist30_h3_off.csv \
        --diagnose results/chase_diagnose_h3on.csv \
        --out results/h3_ab_report.md

Exit codes: 0 başarı, 2 eksik/geçersiz girdi.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "results" / "h3_ab_report.md"

# Karar eşiği: medyan OOS delta bu bandın dışında ise anlamlı sayılır.
DECISION_EPS_PP = 0.10

# Overfitting tanımı (raporda açıkça kullanılır):
#   flag  : WF validator'ın has_overfitting_warning bayraklı ticker payı
#   struct: IS Ort > 0 ama OOS Ort <= 0 olan ticker payı (yapısal overfit)
TRUTHY = {"true", "1", "yes"}

# cp1252 konsollarda UnicodeEncodeError'ı önlemek için yalnızca console
# çıktıları ASCII'ye çevrilir; rapor dosyası UTF-8 kalır.
_CONSOLE_MAP = str.maketrans("ıİşŞğĞçÇöÖüÜ", "iIsSgGcCoOuU")


def _console(text: str) -> str:
    return text.translate(_CONSOLE_MAP)


def load_rows(path: Path) -> list[dict[str, str]]:
    # utf-8-sig: Windows araçlarının eklediği BOM'u tolere eder.
    with path.open("r", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUTHY


def _f(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def ok_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if r.get("status") == "OK"]


def aggregate(rows: list[dict[str, str]]) -> dict[str, float]:
    """Universe aggregate'ı (yalnızca status=OK satırları)."""
    ok = ok_rows(rows)
    oos = [v for v in (_f(r.get("oos_mean_return")) for r in ok) if v is not None]
    n = len(oos)
    if n == 0:
        return {
            "n": 0.0,
            "median_oos": 0.0,
            "mean_oos": 0.0,
            "positive_share": 0.0,
            "overfit_flag_share": 0.0,
            "is_plus_oos_minus_share": 0.0,
        }
    positive = sum(1 for v in oos if v > 0)
    overfit_flags = sum(1 for r in ok if _truthy(r.get("has_overfitting_warning")))
    structured = 0
    for r in ok:
        is_v, oos_v = _f(r.get("is_mean_return")), _f(r.get("oos_mean_return"))
        if is_v is not None and oos_v is not None and is_v > 0 >= oos_v:
            structured += 1
    return {
        "n": float(n),
        "median_oos": statistics.median(oos),
        "mean_oos": statistics.mean(oos),
        "positive_share": 100.0 * positive / n,
        "overfit_flag_share": 100.0 * overfit_flags / n,
        "is_plus_oos_minus_share": 100.0 * structured / n,
    }


def per_ticker_deltas(
    on_rows: list[dict[str, str]], off_rows: list[dict[str, str]]
) -> tuple[list[dict[str, object]], list[str], list[str]]:
    on_map = {r["ticker"]: r for r in ok_rows(on_rows)}
    off_map = {r["ticker"]: r for r in ok_rows(off_rows)}
    deltas: list[dict[str, object]] = []
    for ticker in sorted(set(on_map) & set(off_map)):
        a, b = on_map[ticker], off_map[ticker]
        on_oos, off_oos = _f(a.get("oos_mean_return")), _f(b.get("oos_mean_return"))
        if on_oos is None or off_oos is None:
            continue
        deltas.append(
            {
                "ticker": ticker,
                "on_oos": on_oos,
                "off_oos": off_oos,
                "delta_oos_pp": round(on_oos - off_oos, 4),
                "on_trades": int(a.get("total_oos_trades") or 0),
                "off_trades": int(b.get("total_oos_trades") or 0),
            }
        )
    deltas.sort(key=lambda d: d["delta_oos_pp"], reverse=True)  # type: ignore[arg-type]
    on_only = sorted(set(on_map) - set(off_map))
    off_only = sorted(set(off_map) - set(on_map))
    return deltas, on_only, off_only


def arms_identical(
    deltas: list[dict[str, object]], on_only: list[str], off_only: list[str]
) -> bool:
    if on_only or off_only:
        return False
    if not deltas:
        return False
    return all(d["delta_oos_pp"] == 0 and d["on_trades"] == d["off_trades"] for d in deltas)


def decide(
    on_agg: dict[str, float],
    off_agg: dict[str, float],
    all_identical: bool,
    eps_pp: float = DECISION_EPS_PP,
) -> tuple[str, str]:
    """Mekanik karar: (key, cümle). Karar yalnızca rapor amaçlıdır."""
    if on_agg["n"] == 0 or off_agg["n"] == 0:
        return "no_data", "Karar verilemedi — en az bir kolda başarılı WF satırı yok."
    if all_identical:
        return (
            "redundant",
            "H3 redundant (kill-switch önerilmez) — iki kol birebir aynı "
            "OOS/trade sonuçlarını üretti.",
        )
    delta_median = on_agg["median_oos"] - off_agg["median_oos"]
    if delta_median > eps_pp:
        return (
            "keep",
            f"H3 kalır — medyan OOS farkı {delta_median:+.2f} pp (> +{eps_pp:.2f} pp eşiği).",
        )
    if delta_median < -eps_pp:
        return (
            "kill_switch",
            f"H3 için kill-switch önerilir (chase_block_enabled=False) — medyan OOS "
            f"farkı {delta_median:+.2f} pp (< -{eps_pp:.2f} pp eşiği). Öneri rapor "
            "amaçlıdır; uygulama kullanıcı onayı gerektirir.",
        )
    return (
        "keep",
        f"H3 kalır — etki marjinal (medyan OOS farkı {delta_median:+.2f} pp, "
        f"eşik ±{eps_pp:.2f} pp).",
    )


# Conservative profilin long eşik referansı (diagnose raw-score dağılımı için).
DIAGNOSE_BUY_THRESHOLD = 25.0


def summarize_diagnose(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    rows = load_rows(path)
    if not rows:
        return None
    capped_rows = [r for r in rows if _truthy(r.get("capped"))]
    per_ticker: dict[str, int] = {}
    for r in capped_rows:
        ticker = r.get("ticker", "?")
        per_ticker[ticker] = per_ticker.get(ticker, 0) + 1
    gaps = [
        abs(raw - cap)
        for raw, cap in ((_f(r.get("raw_score")), _f(r.get("capped_score"))) for r in capped_rows)
        if raw is not None and cap is not None
    ]
    raws = [v for v in (_f(r.get("raw_score")) for r in rows) if v is not None]
    high_score_rows = [r for r in rows if _truthy(r.get("high_score"))]
    return {
        "candidates": len(rows),
        "high_score_rows": len(high_score_rows),
        "capped": len(capped_rows),
        "per_ticker_capped": dict(sorted(per_ticker.items(), key=lambda kv: -kv[1])),
        "mean_cap_gap": statistics.mean(gaps) if gaps else None,
        "max_raw": max(raws) if raws else None,
        "rows_raw_ge_buy_threshold": sum(1 for v in raws if v >= DIAGNOSE_BUY_THRESHOLD),
    }


def _fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "YES" if value else "no"
    if isinstance(value, int | float):
        return f"{float(value):.{digits}f}"
    return str(value)


def build_report(
    on_path: Path,
    off_path: Path,
    on_rows: list[dict[str, str]],
    off_rows: list[dict[str, str]],
    diagnose: dict[str, object] | None,
) -> str:
    on_agg, off_agg = aggregate(on_rows), aggregate(off_rows)
    deltas, on_only, off_only = per_ticker_deltas(on_rows, off_rows)
    identical = arms_identical(deltas, on_only, off_only)
    key, sentence = decide(on_agg, off_agg, identical)

    def arm_meta(rows: list[dict[str, str]]) -> str:
        ok = ok_rows(rows)
        if not ok:
            return "n/a"
        r = ok[0]
        return (
            f"gates={r.get('gates', '?')}, buy={r.get('buy_threshold', '?')}, "
            f"ctm={r.get('counter_trend_multiplier', '?')}"
        )

    missing = sorted({r["ticker"] for r in on_rows if r.get("status") != "OK"})
    lines: list[str] = []
    lines.append("# H3 Chase Block A/B Walk-Forward Raporu")
    lines.append("")
    lines.append(f"- Oluşturulma: {datetime.now(UTC).isoformat(timespec='seconds')}")
    lines.append(f"- H3 ON kolu : `{on_path}` ({arm_meta(on_rows)})")
    lines.append(f"- H3 OFF kolu: `{off_path}` ({arm_meta(off_rows)})")
    lines.append("")
    lines.append("## Kısıtlar")
    lines.append("")
    lines.append("- WF cache: yerel parquet, 22.07.2026; period=3y.")
    lines.append(
        f"- Coverage: {int(on_agg['n'])}/{len(on_rows)} ticker OK;"
        + (f" eksik/verisiz: {', '.join(missing)}" if missing else " tüm ticker'lar OK.")
    )
    lines.append(
        "- Overfitting tanımı: (1) flag = WF `has_overfitting_warning` payı; "
        "(2) struct = IS Ort > 0 ama OOS Ort <= 0 ticker payı."
    )
    lines.append(f"- Karar eşiği: medyan OOS delta ±{DECISION_EPS_PP:.2f} pp.")
    lines.append("")
    lines.append("## Universe Aggregate (status=OK)")
    lines.append("")
    lines.append("| Metrik | H3 ON | H3 OFF | Delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    metric_rows = [
        ("ticker OK (n)", "n", 0),
        ("medyan OOS ort %", "median_oos", 2),
        ("mean OOS ort %", "mean_oos", 2),
        ("pozitif OOS payı %", "positive_share", 1),
        ("overfitting share % (flag)", "overfit_flag_share", 1),
        ("IS+/OOS- payı % (struct)", "is_plus_oos_minus_share", 1),
    ]
    for label, key2, digits in metric_rows:
        a, b = on_agg[key2], off_agg[key2]
        lines.append(f"| {label} | {_fmt(a, digits)} | {_fmt(b, digits)} | {_fmt(a - b, digits)} |")
    lines.append("")
    lines.append("## Per-Ticker Delta (oos_mean_return, pp)")
    lines.append("")
    if deltas:
        lines.append("| Ticker | ON OOS% | OFF OOS% | Δ pp | ON trades | OFF trades |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for d in deltas:
            lines.append(
                f"| {d['ticker']} | {_fmt(d['on_oos'])} | {_fmt(d['off_oos'])} | "
                f"{_fmt(d['delta_oos_pp'])} | {d['on_trades']} | {d['off_trades']} |"
            )
    else:
        lines.append("Ortak OK ticker yok — delta tablosu üretilemedi.")
    if on_only or off_only:
        lines.append("")
        lines.append(f"- Kol farkları: yalnız ON={on_only or '[]'}, yalnız OFF={off_only or '[]'}")
    lines.append("")
    lines.append(
        "Not: diagnose CSV'si yalnızca overextended LONG satırlarını loglar ve CCI/direnç "
        "eşiklerinde strict (>, <) kullanır; engine >=/<= ile ve short tarafında da "
        "çalışır. Bu yüzden engine'de cap yiyen short girişleri diagnose'de görünmez; "
        "gerçek etki için iki kolun OOS farkı ve trade sayısı esas alınır."
    )

    sasa_on = next((r for r in ok_rows(on_rows) if r["ticker"] == "SASA.IS"), None)
    sasa_off = next((r for r in ok_rows(off_rows) if r["ticker"] == "SASA.IS"), None)
    lines.append("")
    lines.append("## SASA.IS Odak")
    lines.append("")
    if sasa_on and sasa_off:
        lines.append(
            f"- ON: OOS={_fmt(_f(sasa_on.get('oos_mean_return')))}%, "
            f"IS={_fmt(_f(sasa_on.get('is_mean_return')))}%, "
            f"trades={sasa_on.get('total_oos_trades')}, "
            f"overfit_flag={sasa_on.get('has_overfitting_warning')}"
        )
        lines.append(
            f"- OFF: OOS={_fmt(_f(sasa_off.get('oos_mean_return')))}%, "
            f"IS={_fmt(_f(sasa_off.get('is_mean_return')))}%, "
            f"trades={sasa_off.get('total_oos_trades')}, "
            f"overfit_flag={sasa_off.get('has_overfitting_warning')}"
        )
    else:
        lines.append("- SASA.IS karşılaştırılamadı (bir kolda OK satır yok).")

    lines.append("")
    lines.append("## Chase Diagnose Özeti (H3 ON kolu)")
    lines.append("")
    if diagnose:
        lines.append(f"- chase_candidate_rows (overextended long): {diagnose['candidates']}")
        lines.append(
            f"- raw score max / >= {DIAGNOSE_BUY_THRESHOLD:g} satır: "
            f"{_fmt(diagnose['max_raw'])} / {diagnose['rows_raw_ge_buy_threshold']}"
        )
        lines.append(
            f"- high-score satır (raw > eşik, cap hesaplanan): {diagnose['high_score_rows']}"
        )
        lines.append(f"- h3_actually_capped_rows: {diagnose['capped']}")
        lines.append(f"- ortalama cap boşluğu (raw-capped): {_fmt(diagnose['mean_cap_gap'])}")
        per_ticker = diagnose["per_ticker_capped"]
        if per_ticker:
            top = ", ".join(f"{k}({v})" for k, v in list(per_ticker.items())[:10])
            lines.append(f"- ticker başına capped (top 10): {top}")
        else:
            lines.append("- Capped satır yok (long tarafında eşik üstü skor görülmedi).")
    else:
        lines.append("- Diagnose CSV verilmedi veya boş.")

    lines.append("")
    lines.append("## Karar")
    lines.append("")
    lines.append(f"- Karar anahtarı: `{key}`")
    lines.append(f"- **{sentence}**")
    lines.append("")
    lines.append("Bu rapor yalnızca öneridir; kill-switch uygulaması kullanıcı onayı gerektirir.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H3 walk-forward A/B comparison report")
    parser.add_argument("--on", type=str, required=True, help="H3 ON WF sonuç CSV'si")
    parser.add_argument("--off", type=str, required=True, help="H3 OFF WF sonuç CSV'si")
    parser.add_argument(
        "--diagnose",
        type=str,
        default=None,
        help="İsteğe bağlı chase diagnose CSV'si (H3 ON kolu)",
    )
    parser.add_argument(
        "--out", type=str, default=str(DEFAULT_OUT), help=f"Rapor çıktısı (default: {DEFAULT_OUT})"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    on_path, off_path = Path(args.on), Path(args.off)
    if not on_path.is_file():
        print(_console(f"ERROR: H3 ON CSV bulunamadı: {on_path}"), file=sys.stderr)
        return 2
    if not off_path.is_file():
        print(_console(f"ERROR: H3 OFF CSV bulunamadı: {off_path}"), file=sys.stderr)
        return 2
    on_rows, off_rows = load_rows(on_path), load_rows(off_path)
    if not on_rows or not off_rows:
        print(_console("ERROR: WF CSV'lerinden biri boş."), file=sys.stderr)
        return 2

    diagnose = None
    if args.diagnose:
        diag_path = Path(args.diagnose)
        if diag_path.is_file():
            diagnose = summarize_diagnose(diag_path)
        else:
            print(
                _console(f"WARNING: diagnose CSV bulunamadı, atlanıyor: {diag_path}"),
                file=sys.stderr,
            )

    report = build_report(on_path, off_path, on_rows, off_rows, diagnose)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    key, sentence = decide(
        aggregate(on_rows),
        aggregate(off_rows),
        arms_identical(*per_ticker_deltas(on_rows, off_rows)),
    )
    print(_console(f"DECISION[{key}]: {sentence}"))
    print(_console(f"Report written: {out_path}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
