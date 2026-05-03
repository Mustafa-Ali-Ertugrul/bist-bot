"""Tests for YFinanceProvider retry/backoff hardening."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from bist_bot.config.settings import Settings
from bist_bot.data.providers import YFinanceProvider


def _make_provider(settings_obj: Settings | None = None) -> YFinanceProvider:
    rate_limiter = MagicMock()
    rate_limiter.wait_if_needed = MagicMock()
    return YFinanceProvider(rate_limiter=rate_limiter)


def _mock_settings(max_retries: int = 3, backoff: float = 1.0) -> MagicMock:
    settings_mock = MagicMock()
    settings_mock.data.YFINANCE_MAX_RETRIES = max_retries
    settings_mock.data.YFINANCE_RETRY_BACKOFF_SECONDS = backoff
    settings_mock.data.PROVIDER_BATCH_TIMEOUT_SECONDS = 60
    return settings_mock


class TestRetryableErrorDetection:
    def test_connection_error_is_retryable(self):
        provider = _make_provider()
        assert provider._is_retryable_error(ConnectionError("connection failed"))

    def test_timeout_error_is_retryable(self):
        provider = _make_provider()
        assert provider._is_retryable_error(TimeoutError("timed out"))

    def test_os_error_is_retryable(self):
        provider = _make_provider()
        assert provider._is_retryable_error(OSError("network error"))

    def test_yfinance_error_names_are_retryable(self):
        provider = _make_provider()

        class YFRateLimitError(Exception):
            pass

        class YFDownloadError(Exception):
            pass

        assert provider._is_retryable_error(YFRateLimitError())
        assert provider._is_retryable_error(YFDownloadError())

    def test_value_error_is_not_retryable(self):
        provider = _make_provider()
        assert not provider._is_retryable_error(ValueError("bad value"))

    def test_key_error_is_not_retryable(self):
        provider = _make_provider()
        assert not provider._is_retryable_error(KeyError("missing key"))


class TestFetchHistoryRetry:
    @patch("bist_bot.data.providers.settings")
    def test_first_fail_second_success(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 3
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01

        provider = _make_provider()
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=[
                ConnectionError("first fail"),
                pd.DataFrame({"Close": [100, 101]}),
            ]
        )

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            result = provider.fetch_history("THYAO.IS", "3mo", "1d")

        assert result is not None
        assert len(result) == 2
        assert mock_ticker.history.call_count == 2

    @patch("bist_bot.data.providers.settings")
    def test_all_retries_exhausted(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 2
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01

        provider = _make_provider()
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=ConnectionError("persistent failure"))

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            result = provider.fetch_history("THYAO.IS", "3mo", "1d")

        assert result is None
        assert mock_ticker.history.call_count == 2

    @patch("bist_bot.data.providers.settings")
    def test_non_retryable_error_does_not_retry(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 3
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01

        provider = _make_provider()
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(side_effect=ValueError("bad parameters"))

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            result = provider.fetch_history("THYAO.IS", "3mo", "1d")

        assert result is None
        assert mock_ticker.history.call_count == 1

    @patch("bist_bot.data.providers.settings")
    def test_empty_response_retries(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 2
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01

        provider = _make_provider()
        mock_ticker = MagicMock()
        mock_ticker.history = MagicMock(
            side_effect=[
                pd.DataFrame(),
                pd.DataFrame({"Close": [100, 101]}),
            ]
        )

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            result = provider.fetch_history("THYAO.IS", "3mo", "1d")

        assert result is not None
        assert len(result) == 2
        assert mock_ticker.history.call_count == 2


class TestFetchBatchRetry:
    @patch("bist_bot.data.providers.settings")
    def test_batch_first_fail_second_success(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 3
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01
        mock_settings.data.PROVIDER_BATCH_TIMEOUT_SECONDS = 60

        provider = _make_provider()
        mock_df = pd.DataFrame({"Close": [100, 101]})

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.download = MagicMock(
                side_effect=[
                    ConnectionError("first fail"),
                    mock_df,
                ]
            )
            result = provider.fetch_batch(["THYAO.IS", "GARAN.IS"], "3mo", "1d")

        assert len(result) == 2
        assert mock_yf.download.call_count == 2

    @patch("bist_bot.data.providers.settings")
    def test_batch_all_retries_exhausted(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 2
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01
        mock_settings.data.PROVIDER_BATCH_TIMEOUT_SECONDS = 60

        provider = _make_provider()

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.download = MagicMock(side_effect=ConnectionError("persistent failure"))
            result = provider.fetch_batch(["THYAO.IS"], "3mo", "1d")

        assert result == {}
        assert mock_yf.download.call_count == 2

    @patch("bist_bot.data.providers.settings")
    def test_batch_non_retryable_error_does_not_retry(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 3
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01
        mock_settings.data.PROVIDER_BATCH_TIMEOUT_SECONDS = 60

        provider = _make_provider()

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.download = MagicMock(side_effect=ValueError("bad parameters"))
            result = provider.fetch_batch(["THYAO.IS"], "3mo", "1d")

        assert result == {}
        assert mock_yf.download.call_count == 1

    @patch("bist_bot.data.providers.settings")
    def test_batch_empty_response_retries(self, mock_settings):
        mock_settings.data.YFINANCE_MAX_RETRIES = 2
        mock_settings.data.YFINANCE_RETRY_BACKOFF_SECONDS = 0.01
        mock_settings.data.PROVIDER_BATCH_TIMEOUT_SECONDS = 60

        provider = _make_provider()
        mock_df = pd.DataFrame({"Close": [100, 101]})

        with patch("bist_bot.data.providers.yf") as mock_yf:
            mock_yf.download = MagicMock(
                side_effect=[
                    pd.DataFrame(),
                    mock_df,
                ]
            )
            result = provider.fetch_batch(["THYAO.IS"], "3mo", "1d")

        assert len(result) == 1
        assert mock_yf.download.call_count == 2
