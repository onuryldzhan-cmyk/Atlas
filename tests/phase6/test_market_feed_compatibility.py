"""
Offline contract tests for MarketFeed compatibility adapter.
"""

from __future__ import annotations

import unittest

from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from atlas_finance.market_data.models import (
    MarketCandle,
    MarketPrice,
)
from exchange.market_feed import MarketFeed


class FakeProvider:

    provider_name = "fake_public_provider"

    def __init__(
        self,
    ) -> None:
        self.connected = False

    def connect(
        self,
    ) -> bool:
        self.connected = True
        return True

    def disconnect(
        self,
    ) -> None:
        self.connected = False

    def get_price(
        self,
        symbol: str,
    ) -> MarketPrice:
        return MarketPrice(
            symbol=symbol,
            price=65000.25,
            provider=self.provider_name,
            received_at=datetime.now(UTC),
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ):
        candle = MarketCandle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=datetime(
                2026,
                7,
                27,
                12,
                0,
                tzinfo=UTC,
            ),
            close_time=datetime(
                2026,
                7,
                27,
                12,
                4,
                59,
                tzinfo=UTC,
            ),
            open=64000.0,
            high=65100.0,
            low=63900.0,
            close=65000.0,
            volume=125.5,
            provider=self.provider_name,
            # Real BinancePublicDataProvider metadata contract. The
            # adapter previously read invented key names, so a fake
            # provider that mirrored those names hid the defect.
            metadata={
                "quote_volume": 8125000.0,
                "trades": 1500,
                "taker_buy_base_volume": 60.0,
                "taker_buy_quote_volume": 3900000.0,
            },
        )

        return tuple(
            candle
            for _ in range(limit)
        )


class MarketFeedCompatibilityTests(
    unittest.TestCase,
):

    def setUp(
        self,
    ) -> None:
        self.provider = FakeProvider()

        self.feed = MarketFeed(
            provider=self.provider,
            publish_events=False,
            collect_metrics=False,
        )

    def tearDown(
        self,
    ) -> None:
        try:
            self.feed.stop()
        except Exception:
            pass

    def test_lifecycle_routes_to_provider(
        self,
    ) -> None:
        self.feed.start()

        self.assertTrue(
            self.provider.connected
        )
        self.assertTrue(
            self.feed.connected
        )

        self.feed.stop()

        self.assertFalse(
            self.provider.connected
        )
        self.assertFalse(
            self.feed.connected
        )

    def test_legacy_price_returns_float(
        self,
    ) -> None:
        self.feed.start()

        value = self.feed.price(
            "BTCUSDT"
        )

        self.assertIsInstance(
            value,
            float,
        )
        self.assertEqual(
            value,
            65000.25,
        )

    def test_legacy_candles_return_binance_rows(
        self,
    ) -> None:
        self.feed.start()

        rows = self.feed.candles(
            "BTCUSDT",
            interval="5m",
            limit=2,
        )

        self.assertEqual(
            len(rows),
            2,
        )
        self.assertEqual(
            len(rows[0]),
            12,
        )
        self.assertEqual(
            rows[0][1],
            "64000.0",
        )
        self.assertEqual(
            rows[0][4],
            "65000.0",
        )
        self.assertEqual(
            rows[0][8],
            1500,
        )

    def test_canonical_methods_remain_available(
        self,
    ) -> None:
        self.feed.start()

        price = self.feed.get_price(
            "BTCUSDT"
        )
        candles = self.feed.get_candles(
            "BTCUSDT",
            timeframe="5m",
            limit=1,
        )

        self.assertIsInstance(
            price,
            MarketPrice,
        )
        self.assertIsInstance(
            candles[0],
            MarketCandle,
        )

    def test_unsupported_exchange_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError,
        ):
            MarketFeed(
                "binance_tr",
                provider=self.provider,
            )


if __name__ == "__main__":
    unittest.main()
