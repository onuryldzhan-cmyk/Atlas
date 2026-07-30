"""
Atlas Market Intelligence v6.0

Connects:
- Candle Manager
- Technical Analyzer
- Market Decision Layer
"""


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.MarketIntelligence"
)



class MarketIntelligence:


    VERSION = "6.0"



    def __init__(
        self,
        candle_manager=None,
        technical_analyzer=None
    ):


        self.candle_manager = candle_manager

        self.technical = technical_analyzer


        logger.info(
            "Atlas Market Intelligence v6.0 initialized"
        )



    # ==================================
    # ANALYZE SYMBOL
    # ==================================


    def analyze(
        self,
        symbol
    ):


        candles = self.candle_manager.get_candles(
            symbol
        )


        if not candles:

            return {

                "symbol":symbol,

                "status":"NO_DATA"

            }




        technical = self.technical.analyze(
            candles
        )



        score = technical["score"]



        if score >= 70:

            regime = "BULLISH"


        elif score <= 30:

            regime = "BEARISH"


        else:

            regime = "NEUTRAL"




        return {


            "symbol":
            symbol,


            "market":
            {


                "regime":
                regime,


                "score":
                score

            },


            "technical":
            technical,


            "time":
            datetime.now(
                UTC
            ).isoformat()


        }





    # ==================================
    # MULTI SYMBOL
    # ==================================


    def scan(
        self,
        symbols
    ):


        results=[]


        for symbol in symbols:

            results.append(

                self.analyze(
                    symbol
                )

            )


        return results





    # ==================================
    # STATUS
    # ==================================


    def status(self):

        return {

            "version":
            self.VERSION

        }