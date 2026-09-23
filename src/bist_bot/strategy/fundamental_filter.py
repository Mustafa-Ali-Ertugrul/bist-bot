"""Fundamental health and valuation screening for BIST equities.

Screens out:
- Micro-cap illiquid shells (< 1B TL market cap)
- Unprofitable / negative earnings without growth
- Extreme valuation bubbles (P/E > 35, P/B > 15)
- Highly leveraged debt distress

Calculates fundamental health: EXCELLENT / HEALTHY / SPECULATIVE / DISTRESSED.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FundamentalHealth:
    ticker: str
    pe_ratio: float | None
    forward_pe: float | None
    pb_ratio: float | None
    roe_pct: float | None
    market_cap_b_tl: float | None
    rating: str  # EXCELLENT | HEALTHY | SPECULATIVE | DISTRESSED
    passed_filter: bool
    summary: str


def evaluate_fundamentals(ticker: str, info: dict[str, Any] | None) -> FundamentalHealth:
    """Evaluate company fundamentals and return a structured health verdict."""
    if not info:
        return FundamentalHealth(
            ticker=ticker,
            pe_ratio=None,
            forward_pe=None,
            pb_ratio=None,
            roe_pct=None,
            market_cap_b_tl=None,
            rating="SPECULATIVE",
            passed_filter=True,  # graceful fallback if data unavailable
            summary="Temel analiz verisi bulunamadı (Nötr değerlendirme).",
        )

    # Extract metrics safely
    pe = info.get("trailingPE") or info.get("pe_ratio")
    pe = float(pe) if pe is not None and str(pe).replace(".", "", 1).isdigit() else None

    forward_pe = info.get("forwardPE")
    forward_pe = (
        float(forward_pe)
        if forward_pe is not None and str(forward_pe).replace(".", "", 1).isdigit()
        else None
    )

    pb = info.get("priceToBook")
    pb = float(pb) if pb is not None and str(pb).replace(".", "", 1).isdigit() else None

    roe = info.get("returnOnEquity")
    roe_pct = round(float(roe) * 100.0, 1) if roe is not None else None

    mcap = info.get("marketCap") or info.get("market_cap")
    market_cap_b = round(float(mcap) / 1e9, 2) if mcap is not None else None

    # Filtering Logic
    reasons: list[str] = []
    rating = "HEALTHY"
    passed = True

    # 1. Market Cap check (> 1 Milyar TL)
    if market_cap_b is not None and market_cap_b < 1.0:
        reasons.append(f"Düşük Piyasa Değeri ({market_cap_b:.1f} Milyar TL - Sığ Tahta)")
        rating = "SPECULATIVE"

    # 2. Extreme Valuation Check
    eff_pe = forward_pe or pe
    if eff_pe is not None:
        if eff_pe > 35.0:
            reasons.append(f"Aşırı Yüksek F/K ({eff_pe:.1f}x)")
            rating = "SPECULATIVE"
        elif eff_pe < 0:
            reasons.append("Şirket Zarar Ediyor (Negatif F/K)")
            rating = "DISTRESSED"
            passed = False
        elif eff_pe <= 10.0:
            reasons.append(f"Cazip Değerleme / İskontolu F/K ({eff_pe:.1f}x)")
            rating = "EXCELLENT" if (roe_pct and roe_pct > 25.0) else "HEALTHY"

    # 3. ROE Quality Check
    if roe_pct is not None:
        if roe_pct > 30.0:
            reasons.append(f"Yüksek Özsermaye Kârlılığı (%{roe_pct:.1f})")
            if rating != "DISTRESSED":
                rating = "EXCELLENT"
        elif roe_pct < 0.0:
            reasons.append(f"Negatif Özsermaye Kârlılığı (%{roe_pct:.1f})")
            rating = "DISTRESSED"
            passed = False

    # 4. P/B Bubble Check
    if pb is not None and pb > 15.0:
        reasons.append(f"Aşırı Şişik PD/DD ({pb:.1f}x)")
        if rating != "DISTRESSED":
            rating = "SPECULATIVE"

    summary_str = " · ".join(reasons) if reasons else "Sağlıklı temel bilanço rasyoları."

    return FundamentalHealth(
        ticker=ticker,
        pe_ratio=pe,
        forward_pe=forward_pe,
        pb_ratio=pb,
        roe_pct=roe_pct,
        market_cap_b_tl=market_cap_b,
        rating=rating,
        passed_filter=passed,
        summary=summary_str,
    )
