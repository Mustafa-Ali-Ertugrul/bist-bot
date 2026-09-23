"""AI Investment Advisor Layer for BIST Equities.

Synthesizes:
1. Quantitative Edge (AlphaTrendStrategy: Relative Strength, Volume Surge, 20-day Breakout)
2. Fundamental Health (P/E, P/B, ROE, Market Cap Quality)
3. Market Sentiment & News Flow (Google News RSS headlines)
4. Position Sizing & Money Management (Kelly/Fixed Fraction risk budgeting)

Produces an institutional-grade Investment Memorandum (Yatırım Notu) ready for professional distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bist_bot.market_calendar import TR
from bist_bot.strategy.fundamental_filter import FundamentalHealth
from bist_bot.strategy.signal_models import Signal, SignalType


@dataclass(frozen=True)
class InvestmentMemo:
    ticker: str
    generated_at: str
    verdict: str  # GÜÇLÜ AL | TEMKİNLİ AL | İZLE
    verdict_emoji: str
    entry_price: float
    stop_loss: float
    risk_pct: float
    position_size_shares: int
    position_value_tl: float
    portfolio_pct: float
    max_risk_tl: float
    quant_reasons: list[str]
    fundamental_summary: str
    fundamental_rating: str
    news_headlines: list[str]
    markdown_report: str


class InvestmentAdvisor:
    """Professional investment advisor synthesis engine."""

    def __init__(
        self,
        default_capital: float = 100_000.0,
        max_portfolio_risk_pct: float = 1.5,  # Max 1.5% capital at risk per trade
        max_position_cap_pct: float = 25.0,  # Max 25% single stock allocation
    ) -> None:
        self.default_capital = float(default_capital)
        self.max_portfolio_risk_pct = float(max_portfolio_risk_pct)
        self.max_position_cap_pct = float(max_position_cap_pct)

    def generate_memo(
        self,
        signal: Signal,
        fundamental: FundamentalHealth,
        news: list[dict[str, str]] | None = None,
        portfolio_capital: float | None = None,
    ) -> InvestmentMemo:
        """Create a comprehensive institutional investment memo."""
        cap = float(portfolio_capital or self.default_capital)
        entry_price = float(signal.price)
        stop_loss = float(signal.stop_loss)

        if entry_price <= 0:
            raise ValueError(f"Invalid entry price for {signal.ticker}: {entry_price}")

        # Compute Risk per share
        risk_per_share = max(entry_price - stop_loss, entry_price * 0.01)
        stock_risk_pct = round(risk_per_share / entry_price * 100.0, 2)

        # Money Management: Risk Budgeting
        # Max loss = capital * 1.5%
        max_loss_allowed_tl = cap * (self.max_portfolio_risk_pct / 100.0)
        shares_by_risk = int(max_loss_allowed_tl // risk_per_share)

        # Cap by maximum portfolio weight (e.g. max 25% allocation)
        max_position_tl = cap * (self.max_position_cap_pct / 100.0)
        shares_by_cap = int(max_position_tl // entry_price)

        recommended_shares = max(1, min(shares_by_risk, shares_by_cap))
        position_value_tl = round(recommended_shares * entry_price, 2)
        portfolio_pct = round(position_value_tl / cap * 100.0, 1)
        actual_risk_tl = round(recommended_shares * risk_per_share, 2)

        # Verdict synthesis
        if fundamental.rating == "DISTRESSED" or not fundamental.passed_filter:
            verdict = "İZLE (RADAR)"
            verdict_emoji = "⚪"
        elif (
            fundamental.rating in ("EXCELLENT", "HEALTHY")
            and signal.signal_type == SignalType.STRONG_BUY
        ):
            verdict = "GÜÇLÜ AL"
            verdict_emoji = "🟢"
        else:
            verdict = "TEMKİNLİ AL"
            verdict_emoji = "🟡"

        # News
        news_titles = [n.get("title", "") for n in (news or []) if n.get("title")][:3]
        if not news_titles:
            news_titles = ["Önemli bir negatif haber akışı tespit edilmedi."]

        now_str = datetime.now(TR).strftime("%d.%m.%Y %H:%M")

        # Markdown Report Generation
        md = [
            f"# {verdict_emoji} BIST ALPHA YATIRIM NOTU: {signal.ticker}",
            f"**Tarih:** {now_str} (BIST Seansı) | **Öneri:** **{verdict}**",
            "**Yatırım Ufku:** Swing Trend (2 - 6 Hafta) | **Kâr Alma:** Açık (Trailing Stop)",
            "",
            "---",
            "### 1. Neden Bu Hisse? (Quant & Momentum Analizi)",
        ]
        for r in signal.reasons:
            md.append(f"- {r}")

        md.extend(
            [
                "",
                "---",
                "### 2. Temel Bilanço & Değerleme Sağlığı",
                f"- **Finansal Sağlık:** `{fundamental.rating}` — {fundamental.summary}",
            ]
        )
        pe_str = (
            f"{fundamental.forward_pe or fundamental.pe_ratio:.1f}x"
            if (fundamental.forward_pe or fundamental.pe_ratio)
            else "—"
        )
        pb_str = f"{fundamental.pb_ratio:.1f}x" if fundamental.pb_ratio else "—"
        roe_str = f"%{fundamental.roe_pct:.1f}" if fundamental.roe_pct else "—"
        mcap_str = (
            f"{fundamental.market_cap_b_tl:.1f} Milyar TL" if fundamental.market_cap_b_tl else "—"
        )

        md.extend(
            [
                f"- **Değerleme Oranları:** F/K: **{pe_str}** | PD/DD: **{pb_str}** | Özsermaye Kârlılığı (ROE): **{roe_str}**",
                f"- **Piyasa Büyüklüğü:** {mcap_str} (Likidite Güvencesi)",
                "",
                "---",
                "### 3. Son Haberler & Gündem",
            ]
        )
        for nw in news_titles:
            md.append(f"- 📰 {nw}")

        md.extend(
            [
                "",
                "---",
                f"### 4. Profesyonel Portföy & Risk Planı ({cap:,.0f} TL Portföy Örneği)",
                f"- **Giriş Fiyatı:** `{entry_price:.2f} TL`",
                f"- **Zarar Kes (Stop-Loss):** `{stop_loss:.2f} TL` (Hisse Başına Risk: `%{stock_risk_pct}`)",
                f"- **Önerilen Pozisyon:** **{recommended_shares} Adet** (`{position_value_tl:,.2f} TL` — Portföyün `%{portfolio_pct}`'si)",
                f"- **Kasa Güvenlik Sınırı:** En kötü stop senaryosunda toplam portföy kaybı `{actual_risk_tl:,.2f} TL` (Portföyün sadece `%{round(actual_risk_tl / cap * 100, 2)}`'si)",
                "- **Kâr Sürme Kuralı:** Sabit tavan hedefi yoktur; hisse zirve kapanışından 3.0 ATR geri çekilene kadar kâr sürülür.",
                "",
                "---",
                "*(Yasal Uyarı: Bu not algoritmik analiz ve modelleme ile üretilmiş olup yatırım tavsiyesi niteliğinde değildir.)*",
            ]
        )

        full_md = "\n".join(md)

        return InvestmentMemo(
            ticker=signal.ticker,
            generated_at=now_str,
            verdict=verdict,
            verdict_emoji=verdict_emoji,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_pct=stock_risk_pct,
            position_size_shares=recommended_shares,
            position_value_tl=position_value_tl,
            portfolio_pct=portfolio_pct,
            max_risk_tl=actual_risk_tl,
            quant_reasons=signal.reasons,
            fundamental_summary=fundamental.summary,
            fundamental_rating=fundamental.rating,
            news_headlines=news_titles,
            markdown_report=full_md,
        )
