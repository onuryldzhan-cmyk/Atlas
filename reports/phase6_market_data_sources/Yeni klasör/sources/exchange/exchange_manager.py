"""
Atlas Exchange Manager
"""

from __future__ import annotations

import logging

from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.adapters.binance_tr import BinanceTRExchange


logger = logging.getLogger("AtlasAI.ExchangeManager")


class ExchangeManager:

    def __init__(self, exchange_name: str = "binance_global"):

        self.exchange_name = exchange_name
        self.exchange = self._create_exchange()

    def _create_exchange(self):

        if self.exchange_name == "binance_tr":
            logger.info("Using Binance TR")
            return BinanceTRExchange()

        logger.info("Using Binance Global")
        return BinanceGlobalExchange()

    def connect(self):

        return self.exchange.connect()

    def disconnect(self):

        return self.exchange.disconnect()

    def get_price(self, symbol: str):

        return self.exchange.get_price(symbol)

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500
    ):

        return self.exchange.get_klines(
            symbol,
            interval,
            limit
        )

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ):

        return self.exchange.place_order(
            symbol,
            side,
            quantity
        )