"""Score vs return correlation report (Z3)."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd  # noqa: F401

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


BUCKETS = [(25, 30), (30, 35), (35, 40), (40, 100)]
BUCKET_LABELS = ["25-30", "30-35", "35-40", "40+"]
HOUR_BUCKETS = [(10, 12), (12, 14), (14, 16), (16, 18)]
HOUR_LABELS = ["10-12", "12-14", "14-16", "16-18"]


def _bucket_score(score: float) -> str | None:
    for (lo, hi), label in zip(BUCKETS, BUCKET_LABELS, strict=False):
        if lo <= score < hi or (label == "40+" and score >= 40):
            return label
    return None


def _bucket_hour(hour: int) -> str | None:
    for (lo, hi), label in zip(HOUR_BUCKETS, HOUR_LABELS, strict=False):
        if lo <= hour < hi:
            return label
    return None


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    try:
        import math

        n = len(x)
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=False))
        den_x = sum((xi - mx) ** 2 for xi in x)
        den_y = sum((yi - my) ** 2 for yi in y)
        den = math.sqrt(den_x * den_y)
        if den == 0:
            return 0.0
        return num / den
    except Exception:
        return None


def load_outcomes(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.exists():
        return []
    rows = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                r["score"] = float(r.get("score") or 0)
                r["net_pnl"] = float(r.get("net_pnl") or r.get("net_pnl_pct") or 0)
                r["mfe_pct"] = float(r.get("mfe_pct") or 0)
                r["mae_pct"] = float(r.get("mae_pct") or 0)
                r["entry_ts"] = r.get("entry_ts") or r.get("entry_time") or ""
                r["outcome"] = r.get("outcome") or r.get("exit_reason") or ""
                rows.append(r)
            except Exception:
                continue
    return rows


def compute_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bucket_stats: dict[str, dict[str, Any]] = {
        label: {
            "count": 0,
            "wins": 0,
            "pnl_sum": 0.0,
            "mfe_sum": 0.0,
            "mae_sum": 0.0,
            "holding_sum": 0,
        }
        for label in BUCKET_LABELS
    }
    hour_stats: dict[str, dict[str, Any]] = {
        label: {"count": 0, "wins": 0, "pnl_sum": 0.0} for label in HOUR_LABELS
    }
    scores: list[float] = []
    pnls: list[float] = []
    mfe_scores: list[float] = []
    mfe_vals: list[float] = []
    for r in rows:
        score = float(r["score"])
        pnl = float(r["net_pnl"])
        outcome = str(r.get("outcome", ""))
        is_win = pnl > 0 or outcome == "TARGET_HIT"
        # score bucket
        b = _bucket_score(score)
        if b:
            bs = bucket_stats[b]
            bs["count"] += 1
            if is_win:
                bs["wins"] += 1
            bs["pnl_sum"] += pnl
            bs["mfe_sum"] += float(r.get("mfe_pct", 0))
            bs["mae_sum"] += float(r.get("mae_pct", 0))
            try:
                bs["holding_sum"] += int(float(r.get("holding_min", 0)))
            except Exception:
                pass
        # hour bucket
        try:
            ts_raw = str(r.get("entry_ts", ""))
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            hour = dt.astimezone(UTC).astimezone().hour if dt.tzinfo else dt.hour
            # but entry_ts is UTC, convert to TR? Use UTC hour as proxy; for test use UTC
            # For simplicity, use hour from ts directly if contains T
            # Parse hour via datetime
            hb = _bucket_hour(hour)
            if hb:
                hs = hour_stats[hb]
                hs["count"] += 1
                if is_win:
                    hs["wins"] += 1
                hs["pnl_sum"] += pnl
        except Exception:
            pass
        scores.append(score)
        pnls.append(pnl)
        mfe_scores.append(score)
        mfe_vals.append(float(r.get("mfe_pct", 0)))
    # compute derived
    for label in BUCKET_LABELS:
        bs = bucket_stats[label]
        c = bs["count"]
        bs["win_rate"] = round(bs["wins"] / c * 100, 1) if c else 0.0
        bs["avg_pnl"] = round(bs["pnl_sum"] / c, 2) if c else 0.0
        bs["avg_mfe"] = round(bs["mfe_sum"] / c, 2) if c else 0.0
        bs["avg_mae"] = round(bs["mae_sum"] / c, 2) if c else 0.0
        bs["avg_holding"] = round(bs["holding_sum"] / c, 1) if c else 0.0
    for label in HOUR_LABELS:
        hs = hour_stats[label]
        c = hs["count"]
        hs["win_rate"] = round(hs["wins"] / c * 100, 1) if c else 0.0
        hs["avg_pnl"] = round(hs["pnl_sum"] / c, 2) if c else 0.0
    score_pnl_corr = _pearson(scores, pnls)
    score_mfe_corr = _pearson(mfe_scores, mfe_vals)
    return {
        "bucket_stats": bucket_stats,
        "hour_stats": hour_stats,
        "score_pnl_corr": score_pnl_corr,
        "score_mfe_corr": score_mfe_corr,
        "total": len(rows),
    }


def generate_markdown(stats: dict[str, Any]) -> str:
    total = stats["total"]
    lines = [
        "# Skor\u2194Getiri Korelasyon Raporu",
        "",
        f"Toplam outcome kayd\u0131: **{total}**",
        "",
        "## Skor Bucket'lar\u0131",
        "",
        "| Skor | Adet | Win-rate | Ort. Net PnL | Ort. MFE | Ort. MAE | Ort. Tutma (dk) |",
        "|---|---|---|---|---|---|---|",
    ]
    for label in BUCKET_LABELS:
        bs = stats["bucket_stats"][label]
        lines.append(
            f"| {label} | {bs['count']} | %{bs['win_rate']:.1f} | {bs['avg_pnl']:.2f} | {bs['avg_mfe']:.2f} | {bs['avg_mae']:.2f} | {bs['avg_holding']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Giri\u015f Saati Bucket'lar\u0131",
            "",
            "| Saat | Adet | Win-rate | Ort. Net PnL |",
            "|---|---|---|---|",
        ]
    )
    for label in HOUR_LABELS:
        hs = stats["hour_stats"][label]
        lines.append(f"| {label} | {hs['count']} | %{hs['win_rate']:.1f} | {hs['avg_pnl']:.2f} |")
    lines.append("")
    corr = stats["score_pnl_corr"]
    mfe_corr = stats["score_mfe_corr"]
    if corr is None:
        lines.append("_Skor\u2194pnl korelasyonu i\u00e7in yeterli \u00f6rnek yok (n<30)_")
    else:
        lines.append(f"**Skor\u2194pnl Pearson:** {corr:.3f}")
    if mfe_corr is None:
        lines.append("_Skor\u2194MFE korelasyonu i\u00e7in yeterli \u00f6rnek yok_")
    else:
        lines.append(f"**Skor\u2194MFE Pearson:** {mfe_corr:.3f}")
    if total < 30:
        lines.append("")
        lines.append(f"_Uyar\u0131: toplam n={total} <30, korelasyon g\u00fcvenilir de\u011fil_")
    return "\n".join(lines)


def run(
    csv_path: str | Path = "results/signal_outcomes.csv",
    output_path: str | Path = "results/score_correlation.md",
) -> str:
    csv_p = Path(csv_path)
    out_p = Path(output_path)
    rows = load_outcomes(csv_p)
    stats = compute_stats(rows)
    md = generate_markdown(stats)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(md, encoding="utf-8")
    return md
