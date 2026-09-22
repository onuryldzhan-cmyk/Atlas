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

Lazy re-exports
---------------
Re-exports below are lazy (PEP 562), mirroring ``data_layer/__init__.py``.

``contracts.py`` is a pure L1 market-data contract with no I/O, but importing
it makes Python execute this package's ``__init__.py`` first. While that
``__init__`` eagerly imported ``binance_public_provider`` and
``market_feed_service``, every ``from atlas_finance.market_data.<anything>
import ...`` dragged in a live ``requests`` HTTP client and the market-feed
service as a side effect, regardless of which submodule was actually
requested. That is ARCH-EDGE-001's Group B2, and it is the exact harm the
L1-must-not-depend-on-L2 rule exists to prevent.

Deferring these imports to first attribute access removes that coupling
without changing ``__all__`` or how any name resolves.

Note on the architecture gate: this does **not** clear the two Group B2
forbidden edges. ``find_forbidden_edges`` is a static AST detector and flags
the ancestor-package *execution* edge, which exists no matter what this file
contains. Clearing the gate would require reclassifying this package marker,
which registry v4.45 (GRANT-B2-PHASE-1-LAZY-ONLY) explicitly does not
authorize. The gate staying red on these 2 edges is the expected outcome of
this change, not a defect.

============================================================
"""

from __future__ import annotations

import importlib
from typing import Any


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


_LAZY_ATTRIBUTES = {
    "BinancePublicDataProvider": (
        "atlas_finance.market_data.binance_public_provider",
        "BinancePublicDataProvider",
    ),
    "MarketDataProviderProtocol": (
        "atlas_finance.market_data.contracts",
        "MarketDataProviderProtocol",
    ),
    "InvalidCandleError": ("atlas_finance.market_data.exceptions", "InvalidCandleError"),
    "InvalidCandleLimitError": (
        "atlas_finance.market_data.exceptions",
        "InvalidCandleLimitError",
    ),
    "InvalidPriceError": ("atlas_finance.market_data.exceptions", "InvalidPriceError"),
    "InvalidSymbolError": ("atlas_finance.market_data.exceptions", "InvalidSymbolError"),
    "InvalidTimeframeError": (
        "atlas_finance.market_data.exceptions",
        "InvalidTimeframeError",
    ),
    "MarketDataConfigurationError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataConfigurationError",
    ),
    "MarketDataConnectionError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataConnectionError",
    ),
    "MarketDataError": ("atlas_finance.market_data.exceptions", "MarketDataError"),
    "MarketDataProviderError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataProviderError",
    ),
    "MarketDataProviderUnavailableError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataProviderUnavailableError",
    ),
    "MarketDataRateLimitError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataRateLimitError",
    ),
    "MarketDataRequestError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataRequestError",
    ),
    "MarketDataResponseError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataResponseError",
    ),
    "MarketDataServiceError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataServiceError",
    ),
    "MarketDataServiceNotRunningError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataServiceNotRunningError",
    ),
    "MarketDataServiceShutdownError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataServiceShutdownError",
    ),
    "MarketDataServiceStartupError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataServiceStartupError",
    ),
    "MarketDataTimeoutError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataTimeoutError",
    ),
    "MarketDataValidationError": (
        "atlas_finance.market_data.exceptions",
        "MarketDataValidationError",
    ),
    "MarketFeedEventType": (
        "atlas_finance.market_data.market_feed_service",
        "MarketFeedEventType",
    ),
    "MarketFeedService": (
        "atlas_finance.market_data.market_feed_service",
        "MarketFeedService",
    ),
    "MarketCandle": ("atlas_finance.market_data.models", "MarketCandle"),
    "MarketDataRequestStatistics": (
        "atlas_finance.market_data.models",
        "MarketDataRequestStatistics",
    ),
    "MarketFeedSnapshot": ("atlas_finance.market_data.models", "MarketFeedSnapshot"),
    "MarketFeedStatistics": ("atlas_finance.market_data.models", "MarketFeedStatistics"),
    "MarketPrice": ("atlas_finance.market_data.models", "MarketPrice"),
    "candles_as_dicts": ("atlas_finance.market_data.models", "candles_as_dicts"),
    "immutable_mapping": ("atlas_finance.market_data.models", "immutable_mapping"),
    "utc_now": ("atlas_finance.market_data.models", "utc_now"),
}

# Submodules that the previous eager ``from ... import ...`` statements bound
# onto this package object as an import-system side effect. They are resolved
# here so that ``import atlas_finance.market_data`` followed by
# ``atlas_finance.market_data.models`` keeps working exactly as before. They are
# deliberately absent from ``__all__``, which is unchanged: this preserves
# existing behaviour without widening the public surface.
_LAZY_SUBMODULES = frozenset(
    {
        "binance_public_provider",
        "contracts",
        "exceptions",
        "market_feed_service",
        "models",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_SUBMODULES:
        value = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value

    target = _LAZY_ATTRIBUTES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | _LAZY_SUBMODULES)
