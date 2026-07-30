"""
============================================================
ATLAS MARKET INTELLIGENCE v2.0
============================================================

Analyzes:

- Market regime
- Technical condition
- Sentiment
- Volatility
- Opportunities

Output provider for Market Pipeline

============================================================
"""


import logging
from datetime import datetime, UTC


logger = logging.getLogger(
    "AtlasAI.MarketIntelligence"
)




class MarketIntelligence:


    VERSION = "2.0"



    def __init__(self):

        logger.info(
            "Market Intelligence v2.0 initialized"
        )




    def analyze(

        self,

        symbol,

        candles=None

    ):


        if candles is None:

            candles = []



        volatility = self._calc_volatility(

            candles

        )



        technical = self._technical_analysis(

            candles

        )



        market = self._market_regime(

            technical

        )



        sentiment = self._sentiment()



        opportunity = {


            "symbol":

            symbol,


            "score":

            market["score"],


            "opportunity":

            "GOOD"

            if market["score"] >= 60

            else

            "WEAK",


            "reasons":

            market["reasons"]

        }




        return {


            "time":

            datetime.now(
                UTC
            ).isoformat(),



            "market":

            market,



            "technical":

            technical,



            "sentiment":

            sentiment,



            "volatility":

            volatility,



            "opportunities":

            [

                opportunity

            ]

        }





    # ==================================================
    # MARKET REGIME
    # ==================================================


    def _market_regime(

        self,

        technical

    ):


        score = technical["score"]


        if score >= 70:


            return {

                "regime":

                "BULLISH",


                "score":

                score,


                "reasons":

                [

                    "Strong technical momentum"

                ]

            }



        if score <= 30:


            return {

                "regime":

                "BEARISH",


                "score":

                score,


                "reasons":

                [

                    "Weak market condition"

                ]

            }



        return {


            "regime":

            "NEUTRAL",


            "score":

            score,


            "reasons":

            [

                "Mixed signals"

            ]

        }





    # ==================================================
    # TECHNICAL
    # ==================================================


    def _technical_analysis(

        self,

        candles

    ):


        if len(candles) < 20:


            return {


                "score":

                50,


                "reason":

                "Insufficient data"

            }




        closes = [

            c["close"]

            for c in candles

        ]



        last = closes[-1]


        avg = sum(closes[-20:]) / 20



        score = 60 if last > avg else 40



        return {


            "score":

            score,


            "last_price":

            last,


            "average":

            round(avg,2)

        }





    # ==================================================
    # SENTIMENT
    # ==================================================


    def _sentiment(self):


        return {


            "news":

            "neutral",


            "score":

            50

        }





    # ==================================================
    # VOLATILITY
    # ==================================================


    def _calc_volatility(

        self,

        candles

    ):


        if len(candles)<2:

            return 0



        high=max(

            c["high"]

            for c in candles

        )


        low=min(

            c["low"]

            for c in candles

        )



        if low == 0:

            return 0



        return round(

            (high-low)/low,

            4

        )





    def status(self):


        return {


            "version":

            self.VERSION

        }