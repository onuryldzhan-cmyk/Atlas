"""
Atlas Binance Market Provider v5.0

Live market data connector.
"""


import requests
import logging



logger = logging.getLogger(
    "AtlasAI.BinanceProvider"
)



class BinanceProvider:


    VERSION = "5.0"


    BASE_URL = (
        "https://api.binance.com"
    )



    def __init__(self):

        logger.info(
            "Atlas Binance Provider v5.0 initialized"
        )




    def get_price(
        self,
        symbol
    ):


        url = (
            f"{self.BASE_URL}"
            f"/api/v3/ticker/price"
        )


        response = requests.get(

            url,

            params={
                "symbol":symbol
            },

            timeout=5

        )


        data = response.json()


        return float(
            data["price"]
        )




    def get_volume(
        self,
        symbol
    ):


        url = (
            f"{self.BASE_URL}"
            f"/api/v3/ticker/24hr"
        )


        response = requests.get(

            url,

            params={
                "symbol":symbol
            },

            timeout=5

        )


        data=response.json()


        return float(
            data["volume"]
        )





    def get_candles(
        self,
        symbol,
        timeframe="5m",
        limit=100
    ):


        url = (
            f"{self.BASE_URL}"
            f"/api/v3/klines"
        )


        response=requests.get(

            url,

            params={

                "symbol":symbol,

                "interval":timeframe,

                "limit":limit

            },

            timeout=5

        )



        candles=[]


        for item in response.json():


            candles.append({

                "open":
                float(item[1]),


                "high":
                float(item[2]),


                "low":
                float(item[3]),


                "close":
                float(item[4]),


                "volume":
                float(item[5])

            })



        return candles