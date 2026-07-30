"""
============================================================
ATLAS FINANCE v1.0.0
============================================================

Project Atlas AI

Financial application-service infrastructure running on top
of AtlasOS.

Current capabilities
--------------------
- Public Binance market-data provider
- Provider-independent market-data contract
- AtlasOS-native MarketFeedService
- Immutable market-data models
- Market-data validation
- Market-data exception hierarchy
- Provider lifecycle management
- EventBus integration
- Metrics integration
- Health reporting
- Operational snapshots

Planned capabilities
--------------------
- CandleCacheService
- PriceCacheService
- MarketSnapshotService
- CandleProcessorService
- TechnicalAnalyzerService
- WorldAnalysisService
- AtlasBrainService
- DecisionEngineService
- RiskService
- ExecutionService
- LearningService

Security architecture
---------------------
Public market-data components are intentionally isolated from:

- Order execution
- Portfolio management
- Capital allocation
- Position management
- Account balance access
- Private exchange credentials

============================================================
"""

from __future__ import annotations

from atlas_finance.market_data import (
    BinancePublicDataProvider,
    InvalidCandleError,
    InvalidCandleLimitError,
    InvalidPriceError,
    InvalidSymbolError,
    InvalidTimeframeError,
    MarketCandle,
    MarketDataConfigurationError,
    MarketDataConnectionError,
    MarketDataError,
    MarketDataProviderError,
    MarketDataProviderProtocol,
    MarketDataProviderUnavailableError,
    MarketDataRateLimitError,
    MarketDataRequestError,
    MarketDataRequestStatistics,
    MarketDataResponseError,
    MarketDataServiceError,
    MarketDataServiceNotRunningError,
    MarketDataServiceShutdownError,
    MarketDataServiceStartupError,
    MarketDataTimeoutError,
    MarketDataValidationError,
    MarketFeedEventType,
    MarketFeedService,
    MarketFeedSnapshot,
    MarketFeedStatistics,
    MarketPrice,
    candles_as_dicts,
    immutable_mapping,
    utc_now,
)


__title__ = "Atlas Finance"

__package_name__ = "atlas_finance"

__project__ = "Project Atlas AI"

__version__ = "1.0.0"

__author__ = "Project Atlas AI"

__description__ = (
    "Financial application-service infrastructure "
    "for Project Atlas AI."
)


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
    "__author__",
    "__description__",
    "__package_name__",
    "__project__",
    "__title__",
    "__version__",
    "candles_as_dicts",
    "immutable_mapping",
    "utc_now",
]