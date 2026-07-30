"""
============================================================
ATLAS MARKET DATA MODELS v1.0.0
============================================================

Project Atlas AI

Immutable public models for Atlas market-data services.

Models
------
- MarketPrice
- MarketCandle
- MarketDataRequestStatistics
- MarketFeedStatistics
- MarketFeedSnapshot

============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from types import MappingProxyType
from typing import Any
from typing import Mapping
from typing import Sequence


def utc_now() -> datetime:
    """
    Return a timezone-aware UTC datetime.
    """

    return datetime.now(
        UTC
    )


def immutable_mapping(
    value: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """
    Create an immutable shallow mapping copy.
    """

    return MappingProxyType(
        dict(
            value or {}
        )
    )


@dataclass(
    frozen=True,
    slots=True,
)
class MarketPrice:
    """
    Normalized public market price.
    """

    symbol: str
    price: float
    provider: str
    received_at: datetime
    source_timestamp: datetime | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "metadata",
            immutable_mapping(
                self.metadata
            ),
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "provider": self.provider,
            "received_at": (
                self.received_at.isoformat()
            ),
            "source_timestamp": (
                self.source_timestamp.isoformat()
                if self.source_timestamp
                else None
            ),
            "metadata": dict(
                self.metadata or {}
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class MarketCandle:
    """
    Normalized OHLCV candle.
    """

    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime | None
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    closed: bool = True
    metadata: Mapping[str, Any] | None = None

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "metadata",
            immutable_mapping(
                self.metadata
            ),
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open_time": (
                self.open_time.isoformat()
            ),
            "close_time": (
                self.close_time.isoformat()
                if self.close_time
                else None
            ),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "provider": self.provider,
            "closed": self.closed,
            "metadata": dict(
                self.metadata or {}
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class MarketDataRequestStatistics:
    """
    Statistics for one request category.
    """

    total: int
    successful: int
    failed: int
    retries: int
    last_latency_seconds: float | None
    average_latency_seconds: float | None
    maximum_latency_seconds: float | None
    last_success_at: datetime | None
    last_failure_at: datetime | None

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "retries": self.retries,
            "last_latency_seconds": (
                self.last_latency_seconds
            ),
            "average_latency_seconds": (
                self.average_latency_seconds
            ),
            "maximum_latency_seconds": (
                self.maximum_latency_seconds
            ),
            "last_success_at": (
                self.last_success_at.isoformat()
                if self.last_success_at
                else None
            ),
            "last_failure_at": (
                self.last_failure_at.isoformat()
                if self.last_failure_at
                else None
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class MarketFeedStatistics:
    """
    Complete MarketFeedService statistics.
    """

    price_requests: MarketDataRequestStatistics
    candle_requests: MarketDataRequestStatistics
    started_at: datetime | None
    last_request_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    provider_connected: bool

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "price_requests": (
                self.price_requests.as_dict()
            ),
            "candle_requests": (
                self.candle_requests.as_dict()
            ),
            "started_at": (
                self.started_at.isoformat()
                if self.started_at
                else None
            ),
            "last_request_at": (
                self.last_request_at.isoformat()
                if self.last_request_at
                else None
            ),
            "last_success_at": (
                self.last_success_at.isoformat()
                if self.last_success_at
                else None
            ),
            "last_failure_at": (
                self.last_failure_at.isoformat()
                if self.last_failure_at
                else None
            ),
            "consecutive_failures": (
                self.consecutive_failures
            ),
            "provider_connected": (
                self.provider_connected
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class MarketFeedSnapshot:
    """
    Immutable MarketFeedService operational snapshot.
    """

    service_name: str
    service_version: str
    provider_name: str
    running: bool
    provider_connected: bool
    supported_timeframes: tuple[str, ...]
    maximum_candle_limit: int
    retry_attempts: int
    retry_backoff_seconds: float
    statistics: MarketFeedStatistics
    last_prices: Mapping[str, MarketPrice]
    last_candle_counts: Mapping[str, int]
    captured_at: datetime

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "last_prices",
            MappingProxyType(
                dict(
                    self.last_prices
                )
            ),
        )

        object.__setattr__(
            self,
            "last_candle_counts",
            MappingProxyType(
                dict(
                    self.last_candle_counts
                )
            ),
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "service_name": (
                self.service_name
            ),
            "service_version": (
                self.service_version
            ),
            "provider_name": (
                self.provider_name
            ),
            "running": self.running,
            "provider_connected": (
                self.provider_connected
            ),
            "supported_timeframes": list(
                self.supported_timeframes
            ),
            "maximum_candle_limit": (
                self.maximum_candle_limit
            ),
            "retry_attempts": (
                self.retry_attempts
            ),
            "retry_backoff_seconds": (
                self.retry_backoff_seconds
            ),
            "statistics": (
                self.statistics.as_dict()
            ),
            "last_prices": {
                symbol: price.as_dict()
                for symbol, price
                in self.last_prices.items()
            },
            "last_candle_counts": dict(
                self.last_candle_counts
            ),
            "captured_at": (
                self.captured_at.isoformat()
            ),
        }


def candles_as_dicts(
    candles: Sequence[MarketCandle],
) -> list[dict[str, Any]]:
    """
    Convert a candle collection into serializable dictionaries.
    """

    return [
        candle.as_dict()
        for candle in candles
    ]


__all__ = [
    "MarketCandle",
    "MarketDataRequestStatistics",
    "MarketFeedSnapshot",
    "MarketFeedStatistics",
    "MarketPrice",
    "candles_as_dicts",
    "immutable_mapping",
    "utc_now",
]