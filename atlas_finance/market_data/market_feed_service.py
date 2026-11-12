"""
============================================================
ATLAS MARKET FEED SERVICE v1.0.0
============================================================

Project Atlas AI

AtlasOS-native public market-data service.

Architecture
------------

AtlasOS Kernel
      |
      v
MarketFeedService
      |
      v
MarketDataProviderProtocol
      |
      v
BinancePublicDataProvider


Responsibilities
----------------
- Manage public market-data provider lifecycle
- Fetch normalized market prices
- Fetch normalized OHLCV candles
- Maintain thread-safe request statistics
- Publish market-data events
- Export operational metrics
- Produce health and snapshot information
- Detect consecutive provider failures
- Recover automatically after successful requests


Security boundary
-----------------
This service:

- Cannot place orders
- Cannot access exchange account balances
- Cannot access API trading secrets
- Cannot allocate capital
- Cannot modify positions
- Cannot execute BUY or SELL operations

============================================================
"""

from __future__ import annotations

import logging
import math
import threading

from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from types import MappingProxyType
from typing import Any
from typing import Final
from typing import Mapping
from typing import Sequence

from atlas_os import (
    BaseAtlasService,
    EventBusService,
    EventSeverity,
    MetricsService,
    ServiceIdentity,
    ServiceState,
)

from atlas_finance.market_data.contracts import (
    MarketDataProviderProtocol,
)

from atlas_finance.market_data.exceptions import (
    InvalidCandleLimitError,
    InvalidSymbolError,
    InvalidTimeframeError,
    MarketDataConfigurationError,
    MarketDataError,
    MarketDataProviderUnavailableError,
    MarketDataServiceNotRunningError,
    MarketDataServiceShutdownError,
    MarketDataServiceStartupError,
)

from atlas_finance.market_data.models import (
    MarketCandle,
    MarketDataRequestStatistics,
    MarketFeedSnapshot,
    MarketFeedStatistics,
    MarketPrice,
    utc_now,
)


logger = logging.getLogger(
    "AtlasFinance.MarketFeedService"
)


# =========================================================
# EVENT TYPES
# =========================================================


class MarketFeedEventType:
    """
    MarketFeedService event identifiers.
    """

    SERVICE_STARTED: Final[str] = (
        "MARKET_FEED_SERVICE_STARTED"
    )

    SERVICE_STOPPED: Final[str] = (
        "MARKET_FEED_SERVICE_STOPPED"
    )

    SERVICE_START_FAILED: Final[str] = (
        "MARKET_FEED_SERVICE_START_FAILED"
    )

    SERVICE_STOP_FAILED: Final[str] = (
        "MARKET_FEED_SERVICE_STOP_FAILED"
    )

    PRICE_REQUESTED: Final[str] = (
        "MARKET_PRICE_REQUESTED"
    )

    PRICE_RECEIVED: Final[str] = (
        "MARKET_PRICE_RECEIVED"
    )

    PRICE_REQUEST_FAILED: Final[str] = (
        "MARKET_PRICE_REQUEST_FAILED"
    )

    CANDLES_REQUESTED: Final[str] = (
        "MARKET_CANDLES_REQUESTED"
    )

    CANDLES_RECEIVED: Final[str] = (
        "MARKET_CANDLES_RECEIVED"
    )

    CANDLES_REQUEST_FAILED: Final[str] = (
        "MARKET_CANDLES_REQUEST_FAILED"
    )

    PROVIDER_DEGRADED: Final[str] = (
        "MARKET_DATA_PROVIDER_DEGRADED"
    )

    PROVIDER_RECOVERED: Final[str] = (
        "MARKET_DATA_PROVIDER_RECOVERED"
    )


# =========================================================
# INTERNAL STATISTICS STATE
# =========================================================


@dataclass(
    slots=True,
)
class _MutableRequestStatistics:
    """
    Internal mutable request statistics.
    """

    total: int = 0
    successful: int = 0
    failed: int = 0
    retries: int = 0

    latency_total_seconds: float = 0.0

    last_latency_seconds: float | None = None

    maximum_latency_seconds: float | None = None

    last_success_at: datetime | None = None

    last_failure_at: datetime | None = None

    def record_success(
        self,
        *,
        latency_seconds: float,
        timestamp: datetime,
    ) -> None:
        self.total += 1
        self.successful += 1

        self.last_latency_seconds = (
            latency_seconds
        )

        self.latency_total_seconds += (
            latency_seconds
        )

        if (
            self.maximum_latency_seconds
            is None
            or latency_seconds
            > self.maximum_latency_seconds
        ):
            self.maximum_latency_seconds = (
                latency_seconds
            )

        self.last_success_at = timestamp

    def record_failure(
        self,
        *,
        latency_seconds: float,
        timestamp: datetime,
    ) -> None:
        self.total += 1
        self.failed += 1

        self.last_latency_seconds = (
            latency_seconds
        )

        self.latency_total_seconds += (
            latency_seconds
        )

        if (
            self.maximum_latency_seconds
            is None
            or latency_seconds
            > self.maximum_latency_seconds
        ):
            self.maximum_latency_seconds = (
                latency_seconds
            )

        self.last_failure_at = timestamp

    def snapshot(
        self,
    ) -> MarketDataRequestStatistics:
        average_latency: float | None

        if self.total > 0:
            average_latency = (
                self.latency_total_seconds
                / self.total
            )

        else:
            average_latency = None

        return MarketDataRequestStatistics(
            total=self.total,
            successful=self.successful,
            failed=self.failed,
            retries=self.retries,
            last_latency_seconds=(
                self.last_latency_seconds
            ),
            average_latency_seconds=(
                average_latency
            ),
            maximum_latency_seconds=(
                self.maximum_latency_seconds
            ),
            last_success_at=(
                self.last_success_at
            ),
            last_failure_at=(
                self.last_failure_at
            ),
        )


# =========================================================
# MARKET FEED SERVICE
# =========================================================


class MarketFeedService(
    BaseAtlasService
):
    """
    AtlasOS-native public market-data service.
    """

    VERSION: Final[str] = "1.0.0"

    SERVICE_NAME: Final[str] = (
        "MarketFeedService"
    )

    SERVICE_TYPE: Final[str] = (
        "FINANCIAL_MARKET_DATA"
    )

    DESCRIPTION: Final[str] = (
        "AtlasOS public market-price and candle "
        "data service."
    )

    DEFAULT_FAILURE_THRESHOLD: Final[int] = 3

    METRIC_PRICE_REQUESTS: Final[str] = (
        "atlas_market_price_requests_total"
    )

    METRIC_PRICE_FAILURES: Final[str] = (
        "atlas_market_price_failures_total"
    )

    METRIC_PRICE_LATENCY: Final[str] = (
        "atlas_market_price_latency_seconds"
    )

    METRIC_CANDLE_REQUESTS: Final[str] = (
        "atlas_market_candle_requests_total"
    )

    METRIC_CANDLE_FAILURES: Final[str] = (
        "atlas_market_candle_failures_total"
    )

    METRIC_CANDLE_LATENCY: Final[str] = (
        "atlas_market_candle_latency_seconds"
    )

    METRIC_CONSECUTIVE_FAILURES: Final[str] = (
        "atlas_market_consecutive_failures"
    )

    METRIC_PROVIDER_CONNECTED: Final[str] = (
        "atlas_market_provider_connected"
    )

    METRIC_LAST_PRICE: Final[str] = (
        "atlas_market_last_price"
    )

    def __init__(
        self,
        *,
        provider: MarketDataProviderProtocol,
        event_bus: EventBusService | None = None,
        metrics: MetricsService | None = None,
        publish_events: bool = True,
        collect_metrics: bool = True,
        failure_threshold: int = (
            DEFAULT_FAILURE_THRESHOLD
        ),
    ) -> None:
        super().__init__(
            ServiceIdentity(
                name=self.SERVICE_NAME,
                version=self.VERSION,
                service_type=self.SERVICE_TYPE,
                description=self.DESCRIPTION,
            )
        )

        if not isinstance(
            provider,
            MarketDataProviderProtocol,
        ):
            raise MarketDataConfigurationError(
                "provider must implement "
                "MarketDataProviderProtocol."
            )

        self._failure_threshold = (
            self._validate_failure_threshold(
                failure_threshold
            )
        )

        self._provider = provider

        self._event_bus = event_bus

        self._metrics = metrics

        self._publish_events = bool(
            publish_events
        )

        self._collect_metrics = bool(
            collect_metrics
        )

        self._lock = threading.RLock()

        self._price_statistics = (
            _MutableRequestStatistics()
        )

        self._candle_statistics = (
            _MutableRequestStatistics()
        )

        self._last_prices: dict[
            str,
            MarketPrice,
        ] = {}

        self._last_candle_counts: dict[
            str,
            int,
        ] = {}

        self._service_started_at: (
            datetime | None
        ) = None

        self._last_request_at: (
            datetime | None
        ) = None

        self._last_success_at: (
            datetime | None
        ) = None

        self._last_failure_at: (
            datetime | None
        ) = None

        self._consecutive_failures = 0

        self._degradation_active = False

        # Task 013 (registry v5.97): observation only - how often the provider degraded and
        # recovered, and when. Read by health details; never read by any decision.
        self._degradations = 0
        self._recoveries = 0
        self._last_degraded_at: datetime | None = None
        self._last_recovered_at: datetime | None = None

        logger.info(
            "%s v%s initialized with provider %s.",
            self.SERVICE_NAME,
            self.VERSION,
            self._provider.provider_name,
        )

    # =====================================================
    # PUBLIC PROPERTIES
    # =====================================================

    @property
    def provider(
        self,
    ) -> MarketDataProviderProtocol:
        return self._provider

    @property
    def provider_name(
        self,
    ) -> str:
        return self._provider.provider_name

    @property
    def provider_connected(
        self,
    ) -> bool:
        return bool(
            self._provider.connected
        )

    @property
    def failure_threshold(
        self,
    ) -> int:
        return self._failure_threshold

    @property
    def publish_events(
        self,
    ) -> bool:
        return self._publish_events

    @property
    def collect_metrics(
        self,
    ) -> bool:
        return self._collect_metrics

    @property
    def consecutive_failures(
        self,
    ) -> int:
        with self._lock:
            return self._consecutive_failures

    # =====================================================
    # ATLASOS LIFECYCLE
    # =====================================================

    def _on_start(
        self,
    ) -> None:
        try:
            connected = self._provider.connect()

            if not connected:
                raise MarketDataProviderUnavailableError(
                    "Market-data provider returned "
                    "an unsuccessful connection result."
                )

            started_at = utc_now()

            with self._lock:
                self._service_started_at = (
                    started_at
                )

                self._consecutive_failures = 0

                self._degradation_active = False

            self._set_provider_connected_metric(
                True
            )

            self._publish_event(
                MarketFeedEventType.SERVICE_STARTED,
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "version": self.VERSION,
                    "started_at": (
                        started_at.isoformat()
                    ),
                },
            )

            logger.info(
                "%s started successfully.",
                self.SERVICE_NAME,
            )

        except Exception as error:
            self._set_provider_connected_metric(
                False
            )

            self._publish_event(
                (
                    MarketFeedEventType
                    .SERVICE_START_FAILED
                ),
                severity=EventSeverity.CRITICAL,
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "error_type": (
                        type(error).__name__
                    ),
                    "error": str(
                        error
                    ),
                },
            )

            raise MarketDataServiceStartupError(
                "MarketFeedService startup failed."
            ) from error

    def _on_stop(
        self,
    ) -> None:
        try:
            self._provider.disconnect()

            self._set_provider_connected_metric(
                False
            )

            stopped_at = utc_now()

            self._publish_event(
                MarketFeedEventType.SERVICE_STOPPED,
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "stopped_at": (
                        stopped_at.isoformat()
                    ),
                },
            )

            logger.info(
                "%s stopped successfully.",
                self.SERVICE_NAME,
            )

        except Exception as error:
            self._publish_event(
                (
                    MarketFeedEventType
                    .SERVICE_STOP_FAILED
                ),
                severity=EventSeverity.ERROR,
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "error_type": (
                        type(error).__name__
                    ),
                    "error": str(
                        error
                    ),
                },
            )

            raise MarketDataServiceShutdownError(
                "MarketFeedService shutdown failed."
            ) from error

    # =====================================================
    # PUBLIC MARKET DATA API
    # =====================================================

    def get_price(
        self,
        symbol: str,
        *,
        correlation_id: str | None = None,
    ) -> MarketPrice:
        """
        Return the latest normalized market price.
        """

        self._require_running()

        normalized_symbol = (
            self._normalize_symbol(
                symbol
            )
        )

        requested_at = utc_now()

        with self._lock:
            self._last_request_at = requested_at

        self._publish_event(
            MarketFeedEventType.PRICE_REQUESTED,
            payload={
                "symbol": normalized_symbol,
                "provider": self.provider_name,
            },
            correlation_id=correlation_id,
        )

        started = perf_counter()

        try:
            price = self._provider.get_price(
                normalized_symbol
            )

            self._validate_price_result(
                price,
                expected_symbol=(
                    normalized_symbol
                ),
            )

        except Exception as error:
            latency = self._safe_latency(
                started
            )

            self._record_failure(
                request_type="price",
                symbol=normalized_symbol,
                latency_seconds=latency,
                error=error,
                correlation_id=correlation_id,
            )

            raise

        latency = self._safe_latency(
            started
        )

        self._record_price_success(
            price=price,
            latency_seconds=latency,
            correlation_id=correlation_id,
        )

        return price

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
        *,
        correlation_id: str | None = None,
    ) -> tuple[MarketCandle, ...]:
        """
        Return normalized OHLCV candles.
        """

        self._require_running()

        normalized_symbol = (
            self._normalize_symbol(
                symbol
            )
        )

        normalized_timeframe = (
            self._normalize_timeframe(
                timeframe
            )
        )

        normalized_limit = (
            self._validate_limit(
                limit
            )
        )

        requested_at = utc_now()

        with self._lock:
            self._last_request_at = requested_at

        self._publish_event(
            MarketFeedEventType.CANDLES_REQUESTED,
            payload={
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
                "limit": normalized_limit,
                "provider": self.provider_name,
            },
            correlation_id=correlation_id,
        )

        started = perf_counter()

        try:
            received = self._provider.get_candles(
                normalized_symbol,
                normalized_timeframe,
                normalized_limit,
            )

            candles = tuple(
                received
            )

            self._validate_candle_results(
                candles,
                expected_symbol=(
                    normalized_symbol
                ),
                expected_timeframe=(
                    normalized_timeframe
                ),
                maximum_count=(
                    normalized_limit
                ),
            )

        except Exception as error:
            latency = self._safe_latency(
                started
            )

            self._record_failure(
                request_type="candles",
                symbol=normalized_symbol,
                latency_seconds=latency,
                error=error,
                correlation_id=correlation_id,
                extra_payload={
                    "timeframe": (
                        normalized_timeframe
                    ),
                    "limit": normalized_limit,
                },
            )

            raise

        latency = self._safe_latency(
            started
        )

        self._record_candle_success(
            symbol=normalized_symbol,
            timeframe=normalized_timeframe,
            candles=candles,
            latency_seconds=latency,
            correlation_id=correlation_id,
        )

        return candles

    def last_price(
        self,
        symbol: str,
    ) -> MarketPrice | None:
        """
        Return the last successfully received price.
        """

        normalized_symbol = (
            self._normalize_symbol(
                symbol
            )
        )

        with self._lock:
            return self._last_prices.get(
                normalized_symbol
            )

    def statistics(
        self,
    ) -> MarketFeedStatistics:
        """
        Return an immutable service statistics snapshot.
        """

        with self._lock:
            return MarketFeedStatistics(
                price_requests=(
                    self._price_statistics
                    .snapshot()
                ),
                candle_requests=(
                    self._candle_statistics
                    .snapshot()
                ),
                started_at=(
                    self._service_started_at
                ),
                last_request_at=(
                    self._last_request_at
                ),
                last_success_at=(
                    self._last_success_at
                ),
                last_failure_at=(
                    self._last_failure_at
                ),
                consecutive_failures=(
                    self._consecutive_failures
                ),
                provider_connected=(
                    self.provider_connected
                ),
            )

    def market_feed_snapshot(
        self,
    ) -> MarketFeedSnapshot:
        """
        Return a complete immutable market-feed snapshot.
        """

        with self._lock:
            last_prices = dict(
                self._last_prices
            )

            last_candle_counts = dict(
                self._last_candle_counts
            )

        supported_timeframes = tuple(
            getattr(
                self._provider,
                "supported_timeframes",
                (),
            )
        )

        maximum_candle_limit = int(
            getattr(
                self._provider,
                "maximum_candle_limit",
                1000,
            )
        )

        retry_attempts = int(
            getattr(
                self._provider,
                "retry_attempts",
                1,
            )
        )

        retry_backoff_seconds = float(
            getattr(
                self._provider,
                "retry_backoff_seconds",
                0.0,
            )
        )

        return MarketFeedSnapshot(
            service_name=self.SERVICE_NAME,
            service_version=self.VERSION,
            provider_name=self.provider_name,
            running=self.is_running,
            provider_connected=(
                self.provider_connected
            ),
            supported_timeframes=(
                supported_timeframes
            ),
            maximum_candle_limit=(
                maximum_candle_limit
            ),
            retry_attempts=retry_attempts,
            retry_backoff_seconds=(
                retry_backoff_seconds
            ),
            statistics=self.statistics(),
            last_prices=last_prices,
            last_candle_counts=(
                last_candle_counts
            ),
            captured_at=utc_now(),
        )

    # =====================================================
    # BASE SERVICE OBSERVABILITY
    # =====================================================

    def _health_details(
        self,
    ) -> Mapping[str, Any]:
        statistics = self.statistics()

        return MappingProxyType(
            {
                "provider": (
                    self.provider_name
                ),
                "provider_connected": (
                    self.provider_connected
                ),
                "consecutive_failures": (
                    statistics
                    .consecutive_failures
                ),
                "failure_threshold": (
                    self._failure_threshold
                ),
                "price_requests": (
                    statistics
                    .price_requests
                    .total
                ),
                "price_failures": (
                    statistics
                    .price_requests
                    .failed
                ),
                "candle_requests": (
                    statistics
                    .candle_requests
                    .total
                ),
                "candle_failures": (
                    statistics
                    .candle_requests
                    .failed
                ),
                "last_request_at": (
                    statistics
                    .last_request_at
                    .isoformat()
                    if statistics
                    .last_request_at
                    else None
                ),
                "last_success_at": (
                    statistics
                    .last_success_at
                    .isoformat()
                    if statistics
                    .last_success_at
                    else None
                ),
                "last_failure_at": (
                    statistics
                    .last_failure_at
                    .isoformat()
                    if statistics
                    .last_failure_at
                    else None
                ),
                # Task 013 (registry v5.97): DEGRADED -> recovered transitions.
                "degradations": self._degradations,
                "recoveries": self._recoveries,
                "last_degraded_at": (
                    self._last_degraded_at.isoformat()
                    if self._last_degraded_at
                    else None
                ),
                "last_recovered_at": (
                    self._last_recovered_at.isoformat()
                    if self._last_recovered_at
                    else None
                ),
            }
        )

    def _snapshot_metadata(
        self,
    ) -> Mapping[str, Any]:
        snapshot = self.market_feed_snapshot()

        return MappingProxyType(
            {
                "provider": (
                    snapshot.provider_name
                ),
                "provider_connected": (
                    snapshot
                    .provider_connected
                ),
                "supported_timeframes": (
                    snapshot
                    .supported_timeframes
                ),
                "maximum_candle_limit": (
                    snapshot
                    .maximum_candle_limit
                ),
                "retry_attempts": (
                    snapshot.retry_attempts
                ),
                "retry_backoff_seconds": (
                    snapshot
                    .retry_backoff_seconds
                ),
                "statistics": (
                    snapshot
                    .statistics
                    .as_dict()
                ),
                "last_price_symbols": tuple(
                    snapshot
                    .last_prices
                    .keys()
                ),
                "last_candle_keys": tuple(
                    snapshot
                    .last_candle_counts
                    .keys()
                ),
            }
        )

    # =====================================================
    # SUCCESS RECORDING
    # =====================================================

    def _record_price_success(
        self,
        *,
        price: MarketPrice,
        latency_seconds: float,
        correlation_id: str | None,
    ) -> None:
        timestamp = utc_now()

        with self._lock:
            self._price_statistics.record_success(
                latency_seconds=(
                    latency_seconds
                ),
                timestamp=timestamp,
            )

            self._last_prices[
                price.symbol
            ] = price

            self._last_success_at = timestamp

            was_degraded = (
                self._degradation_active
            )

            self._consecutive_failures = 0

            self._degradation_active = False

        self._increment_metric(
            self.METRIC_PRICE_REQUESTS,
            labels={
                "status": "success",
                "symbol": price.symbol,
                "provider": (
                    self.provider_name
                ),
            },
        )

        self._observe_metric(
            self.METRIC_PRICE_LATENCY,
            latency_seconds,
            labels={
                "symbol": price.symbol,
                "provider": (
                    self.provider_name
                ),
            },
        )

        self._set_metric(
            self.METRIC_LAST_PRICE,
            price.price,
            labels={
                "symbol": price.symbol,
                "provider": (
                    self.provider_name
                ),
            },
        )

        self._set_metric(
            self.METRIC_CONSECUTIVE_FAILURES,
            0.0,
        )

        self._set_provider_connected_metric(
            True
        )

        self._publish_event(
            MarketFeedEventType.PRICE_RECEIVED,
            payload={
                "symbol": price.symbol,
                "price": price.price,
                "provider": price.provider,
                "latency_seconds": (
                    latency_seconds
                ),
                "received_at": (
                    price
                    .received_at
                    .isoformat()
                ),
            },
            correlation_id=correlation_id,
        )

        if self._recover_if_degraded():
            self._publish_event(
                (
                    MarketFeedEventType
                    .PROVIDER_RECOVERED
                ),
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "recovered_at": (
                        timestamp.isoformat()
                    ),
                },
                correlation_id=correlation_id,
            )

    def _record_candle_success(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[MarketCandle],
        latency_seconds: float,
        correlation_id: str | None,
    ) -> None:
        timestamp = utc_now()

        candle_key = (
            f"{symbol}:{timeframe}"
        )

        with self._lock:
            self._candle_statistics.record_success(
                latency_seconds=(
                    latency_seconds
                ),
                timestamp=timestamp,
            )

            self._last_candle_counts[
                candle_key
            ] = len(
                candles
            )

            self._last_success_at = timestamp

            was_degraded = (
                self._degradation_active
            )

            self._consecutive_failures = 0

            self._degradation_active = False

        self._increment_metric(
            self.METRIC_CANDLE_REQUESTS,
            labels={
                "status": "success",
                "symbol": symbol,
                "timeframe": timeframe,
                "provider": (
                    self.provider_name
                ),
            },
        )

        self._observe_metric(
            self.METRIC_CANDLE_LATENCY,
            latency_seconds,
            labels={
                "symbol": symbol,
                "timeframe": timeframe,
                "provider": (
                    self.provider_name
                ),
            },
        )

        self._set_metric(
            self.METRIC_CONSECUTIVE_FAILURES,
            0.0,
        )

        self._set_provider_connected_metric(
            True
        )

        first_open_time = (
            candles[0].open_time.isoformat()
            if candles
            else None
        )

        last_open_time = (
            candles[-1].open_time.isoformat()
            if candles
            else None
        )

        self._publish_event(
            MarketFeedEventType.CANDLES_RECEIVED,
            payload={
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(
                    candles
                ),
                "provider": (
                    self.provider_name
                ),
                "latency_seconds": (
                    latency_seconds
                ),
                "first_open_time": (
                    first_open_time
                ),
                "last_open_time": (
                    last_open_time
                ),
            },
            correlation_id=correlation_id,
        )

        if self._recover_if_degraded():
            self._publish_event(
                (
                    MarketFeedEventType
                    .PROVIDER_RECOVERED
                ),
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "recovered_at": (
                        timestamp.isoformat()
                    ),
                },
                correlation_id=correlation_id,
            )

    # =====================================================
    # FAILURE RECORDING
    # =====================================================

    def _record_failure(
        self,
        *,
        request_type: str,
        symbol: str,
        latency_seconds: float,
        error: Exception,
        correlation_id: str | None,
        extra_payload: Mapping[
            str,
            Any,
        ] | None = None,
    ) -> None:
        timestamp = utc_now()

        with self._lock:
            if request_type == "price":
                self._price_statistics.record_failure(
                    latency_seconds=(
                        latency_seconds
                    ),
                    timestamp=timestamp,
                )

            elif request_type == "candles":
                self._candle_statistics.record_failure(
                    latency_seconds=(
                        latency_seconds
                    ),
                    timestamp=timestamp,
                )

            else:
                raise ValueError(
                    "Unsupported request type: "
                    f"{request_type!r}"
                )

            self._last_failure_at = timestamp

            self._consecutive_failures += 1

            consecutive_failures = (
                self._consecutive_failures
            )

            should_degrade = (
                consecutive_failures
                >= self._failure_threshold
            )

            newly_degraded = (
                should_degrade
                and not self._degradation_active
            )

            if should_degrade:
                self._degradation_active = True

        metric_labels = {
            "status": "failure",
            "symbol": symbol,
            "provider": self.provider_name,
            "error_type": (
                type(error).__name__
            ),
        }

        if request_type == "price":
            self._increment_metric(
                self.METRIC_PRICE_REQUESTS,
                labels=metric_labels,
            )

            self._increment_metric(
                self.METRIC_PRICE_FAILURES,
                labels=metric_labels,
            )

            self._observe_metric(
                self.METRIC_PRICE_LATENCY,
                latency_seconds,
                labels={
                    "symbol": symbol,
                    "provider": (
                        self.provider_name
                    ),
                },
            )

            event_type = (
                MarketFeedEventType
                .PRICE_REQUEST_FAILED
            )

        else:
            self._increment_metric(
                self.METRIC_CANDLE_REQUESTS,
                labels=metric_labels,
            )

            self._increment_metric(
                self.METRIC_CANDLE_FAILURES,
                labels=metric_labels,
            )

            self._observe_metric(
                self.METRIC_CANDLE_LATENCY,
                latency_seconds,
                labels={
                    "symbol": symbol,
                    "provider": (
                        self.provider_name
                    ),
                },
            )

            event_type = (
                MarketFeedEventType
                .CANDLES_REQUEST_FAILED
            )

        self._set_metric(
            self.METRIC_CONSECUTIVE_FAILURES,
            float(
                consecutive_failures
            ),
        )

        self._set_provider_connected_metric(
            self.provider_connected
        )

        payload: dict[
            str,
            Any,
        ] = {
            "symbol": symbol,
            "provider": self.provider_name,
            "latency_seconds": (
                latency_seconds
            ),
            "consecutive_failures": (
                consecutive_failures
            ),
            "failure_threshold": (
                self._failure_threshold
            ),
            "error_type": (
                type(error).__name__
            ),
            "error": str(
                error
            ),
        }

        if extra_payload:
            payload.update(
                dict(
                    extra_payload
                )
            )

        self._publish_event(
            event_type,
            severity=EventSeverity.ERROR,
            payload=payload,
            correlation_id=correlation_id,
        )

        if newly_degraded:
            reason = (
                "Market-data provider reached "
                f"{consecutive_failures} consecutive "
                "request failures."
            )

            newly_degraded = self._degrade_if_still_failing(
                reason
            )

        if newly_degraded:
            self._publish_event(
                (
                    MarketFeedEventType
                    .PROVIDER_DEGRADED
                ),
                severity=EventSeverity.WARNING,
                payload={
                    "provider": (
                        self.provider_name
                    ),
                    "reason": reason,
                    "consecutive_failures": (
                        consecutive_failures
                    ),
                },
                correlation_id=correlation_id,
            )

        logger.error(
            (
                "%s request failed. "
                "symbol=%s provider=%s "
                "latency=%.6f error=%s"
            ),
            request_type,
            symbol,
            self.provider_name,
            latency_seconds,
            error,
        )

    # =====================================================
    # EVENT INTEGRATION
    # =====================================================

    def _publish_event(
        self,
        event_type: str,
        *,
        severity: EventSeverity = (
            EventSeverity.INFO
        ),
        payload: Mapping[
            str,
            Any,
        ] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        if (
            not self._publish_events
            or self._event_bus is None
        ):
            return

        try:
            self._event_bus.publish_event(
                event_type=event_type,
                source=self.SERVICE_NAME,
                payload=payload,
                severity=severity,
                correlation_id=correlation_id,
            )

        except Exception:
            logger.exception(
                (
                    "MarketFeedService event "
                    "publication failed. event=%s"
                ),
                event_type,
            )

    # =====================================================
    # METRICS INTEGRATION
    # =====================================================

    def _increment_metric(
        self,
        name: str,
        *,
        amount: float = 1.0,
        labels: Mapping[
            str,
            Any,
        ] | None = None,
    ) -> None:
        if (
            not self._collect_metrics
            or self._metrics is None
        ):
            return

        try:
            self._metrics.increment(
                name,
                amount,
                labels=labels,
            )

        except Exception:
            logger.exception(
                "Metric increment failed: %s",
                name,
            )

    def _observe_metric(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[
            str,
            Any,
        ] | None = None,
    ) -> None:
        if (
            not self._collect_metrics
            or self._metrics is None
        ):
            return

        try:
            self._metrics.observe(
                name,
                value,
                labels=labels,
            )

        except Exception:
            logger.exception(
                "Metric observation failed: %s",
                name,
            )

    def _set_metric(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[
            str,
            Any,
        ] | None = None,
    ) -> None:
        if (
            not self._collect_metrics
            or self._metrics is None
        ):
            return

        try:
            self._metrics.set_gauge(
                name,
                value,
                labels=labels,
            )

        except Exception:
            logger.exception(
                "Metric gauge update failed: %s",
                name,
            )

    def _set_provider_connected_metric(
        self,
        connected: bool,
    ) -> None:
        self._set_metric(
            self.METRIC_PROVIDER_CONNECTED,
            1.0 if connected else 0.0,
            labels={
                "provider": (
                    self.provider_name
                ),
            },
        )

    # =====================================================
    # VALIDATION
    # =====================================================

    def _recover_if_degraded(
        self,
    ) -> bool:
        """Task 010 (reviews 20 F-6, 21 L-3): a success recovers a DEGRADED service.

        Decided and applied under the one service lock (BaseAtlasService uses the same RLock), so it
        recovers only a degradation no newer failure streak still owns: a success racing a failure
        can neither raise, nor leave the service stuck in DEGRADED, nor clear a degradation that
        failures after it re-established. A stop() racing it waits for the lock and finds the
        state already settled.
        """

        with self._lock:
            if (
                self._degradation_active
                or self.state != ServiceState.DEGRADED
            ):
                return False

            self.recover()  # cannot raise: the state was checked under this same lock
            self._recoveries += 1
            self._last_recovered_at = utc_now()

            return True

    def _degrade_if_still_failing(
        self,
        reason: str,
    ) -> bool:
        """Task 010 (review 21 L-3): mark DEGRADED only while this failure streak is still current."""

        with self._lock:
            if (
                not self._degradation_active
                or self.state != ServiceState.RUNNING
            ):
                return False

            self.mark_degraded(  # cannot raise: the state was checked under this same lock
                reason
            )
            self._degradations += 1
            self._last_degraded_at = utc_now()

            return True

    def _require_running(
        self,
    ) -> None:
        # Task 010 (registry v5.94): a DEGRADED service is still operational (BaseAtlasService
        # health: "operational but degraded"), so it keeps serving requests and the next success
        # recovers it. Refusing it, as before, latched the feed until restart: no request could
        # succeed, so recover() was never reached and every later BUY and SELL decision stopped.
        if self.state not in (ServiceState.RUNNING, ServiceState.DEGRADED):
            raise MarketDataServiceNotRunningError(
                "MarketFeedService must be running "
                "before market data can be requested."
            )

    @staticmethod
    def _validate_failure_threshold(
        value: int,
    ) -> int:
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
        ):
            raise MarketDataConfigurationError(
                "failure_threshold must be an "
                "integer."
            )

        if value < 1 or value > 100:
            raise MarketDataConfigurationError(
                "failure_threshold must be between "
                "1 and 100."
            )

        return value

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        if not isinstance(
            symbol,
            str,
        ):
            raise InvalidSymbolError(
                "Market symbol must be a string."
            )

        normalized = (
            symbol.strip()
            .upper()
            .replace(
                "/",
                "",
            )
            .replace(
                "-",
                "",
            )
            .replace(
                "_",
                "",
            )
        )

        if not normalized:
            raise InvalidSymbolError(
                "Market symbol cannot be empty."
            )

        return normalized

    def _normalize_timeframe(
        self,
        timeframe: str,
    ) -> str:
        if not isinstance(
            timeframe,
            str,
        ):
            raise InvalidTimeframeError(
                "Timeframe must be a string."
            )

        normalized = timeframe.strip()

        if not normalized:
            raise InvalidTimeframeError(
                "Timeframe cannot be empty."
            )

        supported = tuple(
            getattr(
                self._provider,
                "supported_timeframes",
                (),
            )
        )

        if (
            supported
            and normalized not in supported
        ):
            raise InvalidTimeframeError(
                "Unsupported timeframe: "
                f"{normalized!r}. Supported values: "
                f"{supported}"
            )

        return normalized

    def _validate_limit(
        self,
        limit: int,
    ) -> int:
        if (
            isinstance(
                limit,
                bool,
            )
            or not isinstance(
                limit,
                int,
            )
        ):
            raise InvalidCandleLimitError(
                "Candle limit must be an integer."
            )

        maximum_limit = int(
            getattr(
                self._provider,
                "maximum_candle_limit",
                1000,
            )
        )

        if limit < 1 or limit > maximum_limit:
            raise InvalidCandleLimitError(
                "Candle limit must be between "
                f"1 and {maximum_limit}."
            )

        return limit

    @staticmethod
    def _validate_price_result(
        price: MarketPrice,
        *,
        expected_symbol: str,
    ) -> None:
        if not isinstance(
            price,
            MarketPrice,
        ):
            raise MarketDataError(
                "Provider returned an invalid "
                "MarketPrice result."
            )

        if price.symbol != expected_symbol:
            raise MarketDataError(
                "Provider price symbol does not "
                "match the requested symbol."
            )

        if (
            not math.isfinite(
                price.price
            )
            or price.price <= 0
        ):
            raise MarketDataError(
                "Provider returned an invalid price."
            )

    @staticmethod
    def _validate_candle_results(
        candles: Sequence[MarketCandle],
        *,
        expected_symbol: str,
        expected_timeframe: str,
        maximum_count: int,
    ) -> None:
        if len(
            candles
        ) > maximum_count:
            raise MarketDataError(
                "Provider returned more candles "
                "than requested."
            )

        previous_open_time: (
            datetime | None
        ) = None

        for index, candle in enumerate(
            candles
        ):
            if not isinstance(
                candle,
                MarketCandle,
            ):
                raise MarketDataError(
                    "Provider returned an invalid "
                    f"candle at index {index}."
                )

            if (
                candle.symbol
                != expected_symbol
            ):
                raise MarketDataError(
                    "Candle symbol does not match "
                    "the requested symbol."
                )

            if (
                candle.timeframe
                != expected_timeframe
            ):
                raise MarketDataError(
                    "Candle timeframe does not "
                    "match the requested timeframe."
                )

            if (
                previous_open_time is not None
                and candle.open_time
                < previous_open_time
            ):
                raise MarketDataError(
                    "Provider candles are not sorted "
                    "by open time."
                )

            previous_open_time = (
                candle.open_time
            )

    @staticmethod
    def _safe_latency(
        started: float,
    ) -> float:
        latency = perf_counter() - started

        if (
            not math.isfinite(
                latency
            )
            or latency < 0
        ):
            return 0.0

        return latency


__all__ = [
    "MarketFeedEventType",
    "MarketFeedService",
]