"""
Atlas Price Provider v1.0

Market price abstraction layer.

Responsibilities:

- Get current price
- Support live provider
- Support test mode
- Cache last price
- Safe fallback
"""


import logging
from datetime import datetime, UTC


logger = logging.getLogger(
    "AtlasAI.PriceProvider"
)



class PriceProvider:



    VERSION = "1.0"



    def __init__(
        self,
        market_provider=None,
        mode="PAPER"
    ):


        self.market_provider = market_provider

        self.mode = mode


        self.cache = {}



        logger.info(
            "Atlas Price Provider v1.0 initialized"
        )





    # =====================================
    # GET PRICE
    # =====================================


    def get_price(
        self,
        symbol
    ):



        price = None



        #
        # LIVE PROVIDER
        #

        if self.market_provider:


            try:


                price = (
                    self.market_provider
                    .get_price(symbol)
                )


            except Exception as e:


                logger.error(
                    f"Price error {e}"
                )





        #
        # FALLBACK TEST PRICE
        #

        if price is None:


            price = self.cache.get(

                symbol,

                65000

            )





        self.cache[symbol] = price



        return {


            "symbol":
            symbol,


            "price":
            price,


            "mode":
            self.mode,


            "time":
            datetime.now(
                UTC
            ).isoformat()

        }







    # =====================================
    # UPDATE CACHE
    # =====================================


    def update(

        self,

        symbol,

        price

    ):


        self.cache[symbol] = price




    # =====================================
    # STATUS
    # =====================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "mode":
            self.mode,


            "cached_symbols":
            list(
                self.cache.keys()
            )

        }