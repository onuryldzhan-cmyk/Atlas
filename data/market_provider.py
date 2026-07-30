"""
Atlas Market Provider v5.0

Base market data interface.

All market sources must
implement this layer.
"""


from abc import ABC, abstractmethod



class MarketProvider(ABC):


    VERSION = "5.0"



    @abstractmethod
    def get_price(
        self,
        symbol
    ):
        pass



    @abstractmethod
    def get_candles(
        self,
        symbol,
        timeframe="5m",
        limit=100
    ):
        pass



    @abstractmethod
    def get_volume(
        self,
        symbol
    ):
        pass