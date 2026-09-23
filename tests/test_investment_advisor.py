"""Unit tests for Fundamental screening and InvestmentAdvisor memorandum generator."""

from bist_bot.strategy.fundamental_filter import evaluate_fundamentals
from bist_bot.strategy.investment_advisor import InvestmentAdvisor
from bist_bot.strategy.signal_models import Signal, SignalType


def test_fundamental_filter_identifies_healthy_and_distressed():
    healthy_info = {
        "trailingPE": 6.5,
        "forwardPE": 5.2,
        "priceToBook": 1.2,
        "returnOnEquity": 0.35,
        "marketCap": 50_000_000_000,
    }
    h = evaluate_fundamentals("THYAO.IS", healthy_info)
    assert h.passed_filter is True
    assert h.rating == "EXCELLENT"
    assert h.market_cap_b_tl == 50.0

    distressed_info = {
        "trailingPE": -4.0,
        "priceToBook": 22.0,
        "returnOnEquity": -0.15,
        "marketCap": 500_000_000,
    }
    d = evaluate_fundamentals("BATIK.IS", distressed_info)
    assert d.passed_filter is False
    assert d.rating == "DISTRESSED"


def test_investment_advisor_generates_memo_with_position_sizing():
    advisor = InvestmentAdvisor(default_capital=100_000.0, max_portfolio_risk_pct=1.5)

    sig = Signal(
        ticker="ASELS.IS",
        signal_type=SignalType.STRONG_BUY,
        score=30.0,
        price=60.0,
        stop_loss=57.0,  # 3 TL risk (5%)
        target_price=69.0,
        reasons=["Göreceli Güç: XU100'e karşı +%4.2", "Kurumsal Hacim: 2.1x"],
    )

    fund = evaluate_fundamentals(
        "ASELS.IS",
        {
            "forwardPE": 12.0,
            "priceToBook": 3.5,
            "returnOnEquity": 0.28,
            "marketCap": 150_000_000_000,
        },
    )

    news = [{"title": "Aselsan yeni ihracat sözleşmesi imzaladı"}]

    memo = advisor.generate_memo(sig, fund, news=news, portfolio_capital=100_000.0)

    assert memo.ticker == "ASELS.IS"
    assert memo.verdict == "GÜÇLÜ AL"
    assert memo.entry_price == 60.0
    assert memo.stop_loss == 57.0
    assert memo.risk_pct == 5.0

    # Risk budgeting: 100k capital * 1.5% max risk = 1,500 TL max loss
    # Risk per share = 3 TL -> 1500 / 3 = 500 shares
    # Value = 500 * 60 = 30,000 TL (capped by 25% max position = 25,000 TL -> 416 shares)
    assert memo.position_size_shares <= 500
    assert memo.position_value_tl <= 25_500.0
    assert "BIST ALPHA YATIRIM NOTU" in memo.markdown_report
    assert "Aselsan yeni ihracat" in memo.markdown_report
