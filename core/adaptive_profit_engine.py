"""
Atlas Adaptive Profit Engine v1.0

AI driven position management.

Features
--------

- Dynamic profit taking
- Trend aware exits
- Momentum protection
- Emergency exits
- Runner protection

"""


import logging


logger = logging.getLogger(
    "AtlasAI.AdaptiveProfit"
)




class AdaptiveProfitEngine:


    def __init__(self):


        self.version = "1.0"


        logger.info(
            "Adaptive Profit Engine v1.0 initialized"
        )




    # =====================================================
    # MAIN EVALUATION
    # =====================================================


    def evaluate(

        self,

        position,

        market,

        plan

    ):


        current_profit = self._profit(

            position,

            market["price"]

        )


        trend = market.get(

            "trend",

            "UNKNOWN"

        )


        momentum = market.get(

            "momentum",

            0

        )


        confidence = market.get(

            "confidence",

            50

        )



        target = plan.get(

            "target_profit",

            5

        )



        levels = plan.get(

            "profit_levels",

            []

        )



        #
        # Emergency exit
        #

        if self._danger(

            market

        ):


            return {


                "action":
                "FULL_EXIT",


                "reason":
                "Market deterioration"

            }



        #
        # Check profit levels
        #

        for level in levels:


            trigger = level["trigger"]


            if current_profit >= trigger:


                return {


                    "action":
                    "PARTIAL_EXIT",


                    "sell_percent":

                    level["sell_percent"],


                    "profit":

                    current_profit,


                    "reason":

                    "Profit target reached"

                }




        #
        # Strong continuation
        #

        if (

            current_profit >= target * 0.7

            and

            trend == "BULLISH"

            and

            momentum >= 75

            and

            confidence >= 75

        ):


            return {


                "action":
                "HOLD_RUNNER",


                "reason":
                "Strong continuation"

            }



        return {


            "action":
            "HOLD",


            "profit":
            current_profit

        }





    # =====================================================
    # PROFIT CALCULATION
    # =====================================================


    def _profit(

        self,

        position,

        price

    ):


        entry = position.get(

            "entry_price",

            0

        )


        if entry == 0:

            return 0



        return round(

            (

                (price-entry)

                /

                entry

            )

            *

            100,

            2

        )





    # =====================================================
    # MARKET DANGER
    # =====================================================


    def _danger(

        self,

        market

    ):


        trend = market.get(

            "trend"

        )


        confidence = market.get(

            "confidence",

            0

        )


        volume = market.get(

            "volume_strength",

            100

        )



        if (

            trend == "BEARISH"

            and

            confidence >= 80

        ):

            return True



        if volume < 25:

            return True



        return False