"""
Atlas Intelligence Pipeline v7.0

Real Market Intelligence Pipeline
"""


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.Pipeline"
)



class AtlasIntelligencePipeline:


    VERSION = "7.0"



    def __init__(
        self,
        market_intelligence=None
    ):

        self.market = market_intelligence


        logger.info(
            "Atlas Intelligence Pipeline v7.0 initialized"
        )



    # ===================================
    # ANALYZE MARKET
    # ===================================


    def analyze_market(
        self,
        symbols=None
    ):


        if symbols is None:

            symbols=[
                "BTCUSDT",
                "ETHUSDT",
                "BNBUSDT",
                "SOLUSDT",
                "XRPUSDT"
            ]



        results = self.market.scan(
            symbols
        )



        opportunities=[]



        for item in results:


            technical = item.get(
                "technical",
                {}
            )


            score = technical.get(
                "score",
                0
            )



            if score >= 60:


                opportunities.append({

                    "symbol":
                    item["symbol"],


                    "score":
                    score,


                    "price":
                    self.market.candle_manager.last_price(
                        item["symbol"]
                    ),


                    "signal":
                    "BUY",


                    "technical":
                    technical

                })





        best = sorted(

            opportunities,

            key=lambda x:x["score"],

            reverse=True

        )





        return {


            "market":

            results,



            "opportunities":

            best,



            "time":

            datetime.now(
                UTC
            ).isoformat()

        }






    def status(self):

        return {

            "version":
            self.VERSION

        }