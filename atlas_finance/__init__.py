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

Lazy re-exports
---------------
Re-exports below are lazy (PEP 562), mirroring ``data_layer/__init__.py``.

This package marker previously performed an unconditional top-level
``from atlas_finance.market_data import (...)`` of thirty names. Because Python
executes every ancestor package ``__init__`` on the way into a submodule, that
one statement meant importing the pure L1 contract module
``atlas_finance/market_data/contracts.py`` loaded a live ``requests`` HTTP
client, ``BinancePublicDataProvider`` and ``MarketFeedService`` as a side
effect. Measured at commit 1e737a8: 313 modules, for an import that needs a
handful.

That is ARCH-EDGE-001's Group B2 coupling. Deferring resolution to first
attribute access removes it. ``__all__`` is unchanged and every name resolves
to the identical object, now on access rather than at package-import time.

Note on the architecture gate: this does **not** clear the two Group B2
forbidden edges, and is not expected to. ``find_forbidden_edges`` is a static
AST detector that flags the ancestor-package *execution* edge, which exists
regardless of this file's contents. Clearing the gate would require
reclassifying this package marker from L2 to L1, which registry v4.45
(GRANT-B2-PHASE-1-LAZY-ONLY) explicitly does not authorize. The gate staying
red on exactly these 2 edges is this change's predicted outcome.

============================================================
"""

from __future__ import annotations

import importlib
from typing import Any


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

# Every re-exported name resolves through ``atlas_finance.market_data``, which
# is where the previous eager statement imported them from. Pointing at the
# subpackage rather than at each leaf module keeps a single source of truth for
# where each name lives: the subpackage's own lazy table. Importing the
# subpackage is itself now near-free, since it is lazy too.
_LAZY_SOURCE = "atlas_finance.market_data"

_LAZY_ATTRIBUTES = frozenset(
    name for name in __all__ if not name.startswith("__")
)

# ``market_data`` was bound onto this package object as a side effect of the
# previous eager ``from atlas_finance.market_data import ...``. It is resolved
# here so ``import atlas_finance`` followed by ``atlas_finance.market_data``
# keeps working exactly as before. It is deliberately absent from ``__all__``,
# which is unchanged: existing behaviour is preserved without widening the
# public surface.
_LAZY_SUBMODULES = frozenset({"market_data"})


def __getattr__(name: str) -> Any:
    if name in _LAZY_SUBMODULES:
        value = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value

    if name not in _LAZY_ATTRIBUTES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(_LAZY_SOURCE), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | _LAZY_SUBMODULES)
