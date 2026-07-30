"""
Atlas Candle Manager v5.1

Responsible for:
- candle storage
- normalization
- market history preparation
"""


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.CandleManager"
)



class CandleManager:


    VERSION = "5.1"



    def __init__(
        self,
        provider=None
    ):

        self.provider = provider

        self.cache = {}

        logger.info(
            "Atlas Candle Manager v5.1 initialized"
        )



    # =====================================
    # GET MARKET CANDLES
    # =====================================


    def get_candles(
        self,
        symbol,
        timeframe="5m",
        limit=100
    ):


        if not self.provider:

            return []



        candles = self.provider.get_candles(

            symbol,

            timeframe,

            limit

        )


        self.cache[symbol] = {

            "candles": candles,

            "time":
            datetime.now(
                UTC
            ).isoformat()

        }



        return candles





    # =====================================
    # LAST PRICE
    # =====================================


    def last_price(
        self,
        symbol
    ):


        candles = self.cache.get(
            symbol
        )


        if not candles:

            return None



        data = candles["candles"]


        if not data:

            return None



        return data[-1]["close"]






    # =====================================
    # MARKET SNAPSHOT
    # =====================================


    def snapshot(
        self,
        symbol
    ):


        candles = self.get_candles(
            symbol
        )


        if not candles:

            return {

                "symbol":
                symbol,

                "status":
                "NO_DATA"

            }



        last = candles[-1]



        return {

            "symbol":
            symbol,


            "price":
            last["close"],


            "high":
            last["high"],


            "low":
            last["low"],


            "volume":
            last["volume"],


            "candles":
            len(candles),


            "time":
            datetime.now(
                UTC
            ).isoformat()

        }






    # =====================================
    # STATUS
    # =====================================


    def status(self):


        return {

            "version":
            self.VERSION,


            "cached_symbols":
            list(
                self.cache.keys()
            )

        }