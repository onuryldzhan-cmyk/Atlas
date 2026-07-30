"""
============================================================
ATLAS MARKET DATA CONTRACTS v1.0.0
============================================================

Project Atlas AI

Provider-independent contracts for public market data.

Security boundary
-----------------
This contract intentionally contains no order-placement method.

A market-data provider cannot:

- Place orders
- Access portfolio capital
- Open positions
- Close positions
- Modify execution state

============================================================
"""

from __future__ import annotations

from typing import Protocol
from typing import Sequence
from typing import runtime_checkable

from atlas_finance.market_data.models import (
    MarketCandle,
    MarketPrice,
)


@runtime_checkable
class MarketDataProviderProtocol(
    Protocol
):
    """
    Public market-data provider contract.
    """

    @property
    def provider_name(
        self,
    ) -> str:
        """
        Human-readable provider identity.
        """

    @property
    def connected(
        self,
    ) -> bool:
        """
        Return whether the provider is operationally connected.
        """

    def connect(
        self,
    ) -> bool:
        """
        Initialize provider resources.

        Public HTTP providers may implement this by validating
        connectivity and preparing a reusable session.
        """

    def disconnect(
        self,
    ) -> None:
        """
        Release provider resources.
        """

    def get_price(
        self,
        symbol: str,
    ) -> MarketPrice:
        """
        Return the latest normalized market price.
        """

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> Sequence[MarketCandle]:
        """
        Return normalized OHLCV candles.
        """


__all__ = [
    "MarketDataProviderProtocol",
]