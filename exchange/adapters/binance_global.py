"""
Atlas Binance Global Adapter v2.0

Production exchange connector.

Features:

- Safe connection handling
- Automatic reconnect
- Connection validation
- Paper trading protection
- Binance API wrapper

"""


from __future__ import annotations


import logging
import os
import time


from dotenv import load_dotenv
from binance.spot import Spot


from exchange.base_exchange import BaseExchange



load_dotenv()



logger = logging.getLogger(
    "AtlasAI.BinanceGlobal"
)





class BinanceGlobalExchange(BaseExchange):


    VERSION = "2.0"



    def __init__(self):


        self.connected = False


        self.client = None


        self.api_key = os.getenv(
            "BINANCE_API_KEY",
            ""
        )


        self.api_secret = os.getenv(
            "BINANCE_API_SECRET",
            ""
        )



        logger.info(
            "Binance Global Adapter initialized"
        )






    # =====================================
    # CONNECT
    # =====================================


    def connect(self):


        try:


            if self.client is None:


                self.client = Spot(

                    api_key=self.api_key,

                    api_secret=self.api_secret

                )



            # connection test


            self.client.time()



            self.connected = True



            logger.info(
                "Binance Global connected"
            )



            return True



        except Exception as e:


            self.connected = False


            logger.exception(
                f"Binance connection failed: {e}"
            )


            return False







    # =====================================
    # DISCONNECT
    # =====================================


    def disconnect(self):


        self.connected = False


        self.client = None



        logger.info(
            "Binance disconnected"
        )






    # =====================================
    # ENSURE CONNECTION
    # =====================================


    def _ensure_connection(self):


        if not self.connected or self.client is None:


            logger.warning(
                "Binance reconnect required"
            )


            self.connect()



        if self.client is None:


            raise ConnectionError(
                "Binance client unavailable"
            )








    # =====================================
    # PRICE
    # =====================================


    def get_price(
        self,
        symbol
    ):


        self._ensure_connection()



        ticker = self.client.ticker_price(

            symbol=symbol

        )



        return float(
            ticker["price"]
        )








    # =====================================
    # CANDLES
    # =====================================


    def get_klines(

        self,

        symbol,

        interval="1m",

        limit=500

    ):


        self._ensure_connection()



        return self.client.klines(

            symbol=symbol,

            interval=interval,

            limit=limit

        )








    # =====================================
    # ORDER
    # =====================================


    def place_order(

        self,

        symbol,

        side,

        quantity

    ):


        logger.warning(
            "Real order disabled - PAPER MODE"
        )



        return {


            "status":
            "PAPER_ONLY",


            "symbol":
            symbol,


            "side":
            side,


            "quantity":
            quantity


        }