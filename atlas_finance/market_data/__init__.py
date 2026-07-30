"""
============================================================
ATLAS FINANCE MARKET DATA PACKAGE v1.0.0
============================================================

Project Atlas AI

Public market-data infrastructure.

Package capabilities
--------------------
- Public Binance market-data provider
- Provider-independent market-data contract
- AtlasOS-native MarketFeedService
- Immutable market-data models
- Market-data validation
- Market-data exception hierarchy
- Serialization helpers

Security boundary
-----------------
This package is restricted to public market-data operations.

It contains no capability for:

- Order placement
- Account balance access
- Portfolio mutation
- Capital allocation
- Position modification
- Trading credential access

============================================================
"""

from __future__ import annotations

from atlas_finance.market_data.binance_public_provider import (
    BinancePublicDataProvider,
)

from atlas_finance.market_data.contracts import (
    MarketDataProviderProtocol,
)

from atlas_finance.market_data.exceptions import (
    InvalidCandleError,
    InvalidCandleLimitError,
    InvalidPriceError,
    InvalidSymbolError,
    InvalidTimeframeError,
    MarketDataConfigurationError,
    MarketDataConnectionError,
    MarketDataError,
    MarketDataProviderError,
    MarketDataProviderUnavailableError,
    MarketDataRateLimitError,
    MarketDataRequestError,
    MarketDataResponseError,
    MarketDataServiceError,
    MarketDataServiceNotRunningError,
    MarketDataServiceShutdownError,
    MarketDataServiceStartupError,
    MarketDataTimeoutError,
    MarketDataValidationError,
)

from atlas_finance.market_data.market_feed_service import (
    MarketFeedEventType,
    MarketFeedService,
)

from atlas_finance.market_data.models import (
    MarketCandle,
    MarketDataRequestStatistics,
    MarketFeedSnapshot,
    MarketFeedStatistics,
    MarketPrice,
    candles_as_dicts,
    immutable_mapping,
    utc_now,
)


__title__ = "Atlas Finance Market Data"

__package_name__ = "atlas_finance.market_data"

__project__ = "Project Atlas AI"

__version__ = "1.0.0"


__all__ = [
    "BinancePublicDataProvider",
    "InvalidCandleError",
    "InvalidCandleLimitError",
    "InvalidPriceError",
    "InvalidSymbolError",
    "InvalidTimeframeError",
    "MarketCandle",
    "MarketDataConfigurationError",
    "MarketDataConnectionError",
    "MarketDataError",
    "MarketDataProviderError",
    "MarketDataProviderProtocol",
    "MarketDataProviderUnavailableError",
    "MarketDataRateLimitError",
    "MarketDataRequestError",
    "MarketDataRequestStatistics",
    "MarketDataResponseError",
    "MarketDataServiceError",
    "MarketDataServiceNotRunningError",
    "MarketDataServiceShutdownError",
    "MarketDataServiceStartupError",
    "MarketDataTimeoutError",
    "MarketDataValidationError",
    "MarketFeedEventType",
    "MarketFeedService",
    "MarketFeedSnapshot",
    "MarketFeedStatistics",
    "MarketPrice",
    "__package_name__",
    "__project__",
    "__title__",
    "__version__",
    "candles_as_dicts",
    "immutable_mapping",
    "utc_now",
]