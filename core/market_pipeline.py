"""
============================================================
ATLAS MARKET PIPELINE v2.0
============================================================

Connects:

Market Data
     |
Candle Manager
     |
Market Intelligence
     |
Intelligence Core


Responsibilities:

- Receive symbols
- Fetch candles
- Run market analysis
- Generate opportunities


============================================================
"""


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.MarketPipeline"
)




class MarketPipeline:


    VERSION = "2.0"



    def __init__(

        self,

        market_intelligence,

        market_provider=None,

        candle_manager=None

    ):


        self.market_intelligence = market_intelligence


        self.market_provider = market_provider


        self.candle_manager = candle_manager



        logger.info(

            "Atlas Market Pipeline v2.0 initialized"

        )






    # =====================================================
    # MAIN ANALYSIS
    # =====================================================


    def analyze_market(

        self,

        symbols=None

    ):



        if symbols is None:

            symbols = [

                "BTCUSDT"

            ]




        opportunities = []

        analyses = []




        for symbol in symbols:


            try:



                candles = self._get_candles(

                    symbol

                )




                result = self.market_intelligence.analyze(

                    symbol,

                    candles

                )



                analyses.append(

                    result

                )



                opportunities.extend(

                    result.get(

                        "opportunities",

                        []

                    )

                )




            except Exception as e:



                logger.exception(

                    f"Market analysis failed {symbol}"

                )





        market = self._combine_market(

            analyses

        )



        technical = self._combine_technical(

            analyses

        )



        return {


            "time":

            datetime.now(
                UTC
            ).isoformat(),



            "market":

            market,



            "technical":

            technical,



            "opportunities":

            opportunities

        }





    # =====================================================
    # DATA FETCH
    # =====================================================


    def _get_candles(

        self,

        symbol

    ):



        if self.candle_manager:


            return self.candle_manager.get(

                symbol

            )



        if self.market_provider:


            return self.market_provider.get_candles(

                symbol

            )



        return []






    # =====================================================
    # MERGE MARKET
    # =====================================================


    def _combine_market(

        self,

        analyses

    ):


        if not analyses:


            return {


                "regime":

                "UNKNOWN",


                "score":

                0

            }




        scores = [

            a["market"]["score"]

            for a in analyses

        ]



        avg = sum(scores)/len(scores)



        regime = (

            "BULLISH"

            if avg >=60

            else

            "BEARISH"

            if avg <=40

            else

            "NEUTRAL"

        )



        return {


            "regime":

            regime,


            "score":

            round(avg,2)

        }





    # =====================================================
    # TECHNICAL MERGE
    # =====================================================


    def _combine_technical(

        self,

        analyses

    ):


        if not analyses:


            return {}



        return analyses[0].get(

            "technical",

            {}

        )






    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "market_intelligence":

            self.market_intelligence is not None,


            "provider":

            self.market_provider is not None,


            "candle_manager":

            self.candle_manager is not None

        }