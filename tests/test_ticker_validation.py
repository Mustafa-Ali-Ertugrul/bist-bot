import pytest
from bist_bot.data.providers import validate_ticker_symbol, YFinanceProvider
from unittest.mock import MagicMock


def test_validate_ticker_symbol_valid():
    assert validate_ticker_symbol("THYAO") == "THYAO"
    assert validate_ticker_symbol("THYAO.IS") == "THYAO.IS"
    assert validate_ticker_symbol("  kchol.is  ") == "KCHOL.IS"
    assert validate_ticker_symbol("GARAN") == "GARAN"


def test_validate_ticker_symbol_invalid_characters():
    with pytest.raises(ValueError, match="Invalid ticker"):
        validate_ticker_symbol("THYAO; DROP TABLE;")

    with pytest.raises(ValueError, match="Invalid ticker"):
        validate_ticker_symbol("../../../etc/passwd")

    with pytest.raises(ValueError, match="Invalid ticker"):
        validate_ticker_symbol("THYAO$FOO")


def test_yfinance_provider_guards_against_invalid_tickers():
    provider = YFinanceProvider(rate_limiter=MagicMock())
    with pytest.raises(ValueError, match="Invalid ticker"):
        provider.fetch_history("INVALID/PATH", "1mo", "1d")

    with pytest.raises(ValueError, match="Invalid ticker"):
        provider.fetch_batch(["THYAO", "INVALID!TICKER"], "1mo", "1d")
