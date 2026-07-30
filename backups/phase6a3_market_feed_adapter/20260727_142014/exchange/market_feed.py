"""
Atlas Market Feed
"""

from __future__ import annotations

import logging

from exchange.exchange_manager import ExchangeManager


logger = logging.getLogger("AtlasAI.MarketFeed")


class MarketFeed:

    def __init__(self, exchange_name="binance_global"):

        self.manager = ExchangeManager(exchange_name)

    def start(self):

        self.manager.connect()

        logger.info("Market Feed started.")

    def stop(self):

        self.manager.disconnect()

        logger.info("Market Feed stopped.")

    def price(self, symbol):

        return self.manager.get_price(symbol)

    def candles(
        self,
        symbol,
        interval="1m",
        limit=500
    ):

        return self.manager.get_klines(
            symbol,
            interval,
            limit
        )