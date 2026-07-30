"""
============================================================
ATLAS MARKET DATA EXCEPTIONS v1.0.0
============================================================

Project Atlas AI

Exception hierarchy for public market-data infrastructure.

Design goals
------------
- Explicit failure categories
- Provider-independent error handling
- Safe error propagation
- Retry-aware failures
- No execution or trading exceptions

============================================================
"""

from __future__ import annotations


class MarketDataError(Exception):
    """
    Base exception for all Atlas market-data failures.
    """


class MarketDataConfigurationError(
    MarketDataError
):
    """
    Raised when a market-data component is configured incorrectly.
    """


class MarketDataValidationError(
    MarketDataError
):
    """
    Raised when market-data input or output fails validation.
    """


class InvalidSymbolError(
    MarketDataValidationError
):
    """
    Raised when a market symbol is empty or invalid.
    """


class InvalidTimeframeError(
    MarketDataValidationError
):
    """
    Raised when a candle timeframe is invalid or unsupported.
    """


class InvalidCandleLimitError(
    MarketDataValidationError
):
    """
    Raised when a requested candle limit is invalid.
    """


class InvalidPriceError(
    MarketDataValidationError
):
    """
    Raised when a provider returns an invalid price.
    """


class InvalidCandleError(
    MarketDataValidationError
):
    """
    Raised when a provider returns an invalid candle.
    """


class MarketDataProviderError(
    MarketDataError
):
    """
    Base exception for provider-related failures.
    """


class MarketDataProviderUnavailableError(
    MarketDataProviderError
):
    """
    Raised when the configured provider is unavailable.
    """


class MarketDataConnectionError(
    MarketDataProviderError
):
    """
    Raised when a provider connection cannot be established.
    """


class MarketDataTimeoutError(
    MarketDataProviderError
):
    """
    Raised when a provider request exceeds its timeout.
    """


class MarketDataRequestError(
    MarketDataProviderError
):
    """
    Raised when a provider request fails.
    """


class MarketDataResponseError(
    MarketDataProviderError
):
    """
    Raised when a provider response is missing or malformed.
    """


class MarketDataRateLimitError(
    MarketDataProviderError
):
    """
    Raised when a provider rejects a request due to rate limiting.
    """


class MarketDataServiceError(
    MarketDataError
):
    """
    Base exception for MarketFeedService failures.
    """


class MarketDataServiceNotRunningError(
    MarketDataServiceError
):
    """
    Raised when market data is requested before service startup.
    """


class MarketDataServiceStartupError(
    MarketDataServiceError
):
    """
    Raised when MarketFeedService cannot complete startup.
    """


class MarketDataServiceShutdownError(
    MarketDataServiceError
):
    """
    Raised when MarketFeedService cannot complete shutdown.
    """


__all__ = [
    "InvalidCandleError",
    "InvalidCandleLimitError",
    "InvalidPriceError",
    "InvalidSymbolError",
    "InvalidTimeframeError",
    "MarketDataConfigurationError",
    "MarketDataConnectionError",
    "MarketDataError",
    "MarketDataProviderError",
    "MarketDataProviderUnavailableError",
    "MarketDataRateLimitError",
    "MarketDataRequestError",
    "MarketDataResponseError",
    "MarketDataServiceError",
    "MarketDataServiceNotRunningError",
    "MarketDataServiceShutdownError",
    "MarketDataServiceStartupError",
    "MarketDataTimeoutError",
    "MarketDataValidationError",
]