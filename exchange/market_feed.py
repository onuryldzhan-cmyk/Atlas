"""
============================================================
ATLAS MARKET FEED COMPATIBILITY ADAPTER v2.0.0
============================================================

Purpose
-------
Preserve the legacy MarketFeed API while routing public market data
through the AtlasFinance MarketFeedService architecture.

Legacy interface preserved
--------------------------
- start()
- stop()
- price(symbol) -> float
- candles(symbol, interval="1m", limit=500) -> Binance-style rows

Canonical pipeline
------------------
MarketFeed
    |
    v
MarketFeedService
    |
    v
BinancePublicDataProvider

Safety
------
- Public market data only
- Cannot place orders
- Does not require trading credentials
- Supports dependency injection for offline contract tests
============================================================
"""

from __future__ import annotations

import logging

from datetime import datetime
from typing import Any
from typing import Iterable

from atlas_finance.market_data.binance_public_provider import (
    BinancePublicDataProvider,
)
from atlas_finance.market_data.contracts import (
    MarketDataProviderProtocol,
)
from atlas_finance.market_data.exceptions import (
    InvalidCandleError,
)
from atlas_finance.market_data.market_feed_service import (
    MarketFeedService,
)
from atlas_finance.market_data.models import (
    MarketCandle,
    MarketPrice,
)
from atlas_finance.market_data.temporal import (
    to_milliseconds,
)


logger = logging.getLogger(
    "AtlasAI.MarketFeed"
)


class MarketFeed:
    """
    Backward-compatible facade over MarketFeedService.

    The class intentionally keeps the established public API used by
    core.application and core.market_loop while moving data acquisition
    to the normalized AtlasFinance market-data platform.
    """

    VERSION = "2.0.0"

    SUPPORTED_EXCHANGES = {
        "binance",
        "binance_global",
    }

    def __init__(
        self,
        exchange_name: str = "binance_global",
        *,
        provider: MarketDataProviderProtocol | None = None,
        event_bus: Any | None = None,
        metrics: Any | None = None,
        publish_events: bool = True,
        collect_metrics: bool = True,
        failure_threshold: int = (
            MarketFeedService.DEFAULT_FAILURE_THRESHOLD
        ),
    ) -> None:
        normalized_exchange = (
            str(exchange_name)
            .strip()
            .lower()
        )

        if normalized_exchange not in self.SUPPORTED_EXCHANGES:
            raise ValueError(
                "MarketFeed v2 supports public Binance Global data only. "
                f"Unsupported exchange_name={exchange_name!r}."
            )

        self.exchange_name = normalized_exchange

        self.provider = (
            provider
            if provider is not None
            else BinancePublicDataProvider()
        )

        self.service = MarketFeedService(
            provider=self.provider,
            event_bus=event_bus,
            metrics=metrics,
            publish_events=publish_events,
            collect_metrics=collect_metrics,
            failure_threshold=failure_threshold,
        )

        logger.info(
            "MarketFeed compatibility adapter initialized: "
            "exchange=%s provider=%s",
            self.exchange_name,
            self.service.provider_name,
        )

    @property
    def connected(
        self,
    ) -> bool:
        """
        Return provider connection state for legacy status consumers.
        """

        return bool(
            self.service.provider_connected
        )

    def start(
        self,
    ) -> None:
        """
        Start MarketFeedService and its public-data provider.
        """

        self.service.start()

        logger.info(
            "Market Feed started through MarketFeedService."
        )

    def stop(
        self,
    ) -> None:
        """
        Stop MarketFeedService and disconnect its provider.
        """

        self.service.stop()

        logger.info(
            "Market Feed stopped through MarketFeedService."
        )

    def price(
        self,
        symbol: str,
    ) -> float:
        """
        Return the legacy scalar price representation.
        """

        result = self.service.get_price(
            symbol
        )

        if isinstance(result, MarketPrice):
            return float(
                result.price
            )

        # Defensive compatibility for custom protocol implementations.
        if hasattr(result, "price"):
            return float(
                result.price
            )

        return float(
            result
        )

    def candles(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 500,
    ) -> list[list[Any]]:
        """
        Return normalized candles in Binance-compatible kline row format.

        Row format
        ----------
        [
            open_time_ms,
            open,
            high,
            low,
            close,
            volume,
            close_time_ms,
            quote_asset_volume,
            number_of_trades,
            taker_buy_base_volume,
            taker_buy_quote_volume,
            ignore,
        ]

        Positions 7 to 10 carry real provider metadata. Missing
        metadata is not zero: the conversion fails closed rather than
        fabricating a value into a legacy row position.
        """

        results = self.service.get_candles(
            symbol,
            timeframe=interval,
            limit=limit,
        )

        return [
            self._to_legacy_candle_row(
                candle
            )
            for candle in results
        ]

    def get_price(
        self,
        symbol: str,
    ) -> MarketPrice:
        """
        Expose the canonical normalized price API.
        """

        return self.service.get_price(
            symbol
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> tuple[MarketCandle, ...]:
        """
        Expose the canonical normalized candle API.
        """

        return tuple(
            self.service.get_candles(
                symbol,
                timeframe=timeframe,
                limit=limit,
            )
        )

    def statistics(
        self,
    ):
        return self.service.statistics()

    def market_feed_snapshot(
        self,
    ):
        return self.service.market_feed_snapshot()

    def health(
        self,
    ):
        """
        Return the underlying Atlas service health response.
        """

        return self.service.health()

    @staticmethod
    def _to_legacy_candle_row(
        candle: MarketCandle,
    ) -> list[Any]:
        metadata = dict(
            candle.metadata or {}
        )

        return [
            MarketFeed._to_milliseconds(
                candle.open_time
            ),
            str(candle.open),
            str(candle.high),
            str(candle.low),
            str(candle.close),
            str(candle.volume),
            MarketFeed._to_milliseconds(
                candle.close_time
                or candle.open_time
            ),
            str(
                MarketFeed._require_metadata(
                    metadata,
                    "quote_volume",
                    candle,
                )
            ),
            int(
                MarketFeed._require_metadata(
                    metadata,
                    "trades",
                    candle,
                )
            ),
            str(
                MarketFeed._require_metadata(
                    metadata,
                    "taker_buy_base_volume",
                    candle,
                )
            ),
            str(
                MarketFeed._require_metadata(
                    metadata,
                    "taker_buy_quote_volume",
                    candle,
                )
            ),
            metadata.get(
                "ignore",
                "0",
            ),
        ]

    @staticmethod
    def _require_metadata(
        metadata: dict[str, Any],
        key: str,
        candle: MarketCandle,
    ) -> Any:
        """
        Return a required provider metadata value.

        Missing is not zero. A None or absent value fails closed with
        the market-data validation semantics instead of fabricating a
        neutral number that a consumer would read as real volume or a
        real trade count.
        """

        value = metadata.get(
            key
        )

        if value is None:
            raise InvalidCandleError(
                f"Candle metadata is missing required field {key!r} "
                f"for {candle.symbol} {candle.timeframe} at "
                f"{candle.open_time.isoformat()}."
            )

        return value

    @staticmethod
    def _to_milliseconds(
        value: datetime,
    ) -> int:
        """
        Convert an aware candle timestamp to epoch milliseconds.

        Naive datetimes are rejected by the temporal authority so the
        host timezone cannot alter a normalized row timestamp.
        """

        return to_milliseconds(
            value
        )
