"""
Atlas Dynamic Profit Engine v2.0

Adaptive profit taking system.

Features
--------
- AI expected move based targets
- Dynamic partial exits
- Trend continuation holding
- Trailing profit protection
- Full exit detection
- Re-entry support preparation

"""


import logging


logger = logging.getLogger(
    "AtlasAI.DynamicProfitEngine"
)



class DynamicProfitEngine:


    def __init__(self):

        self.version = "2.0"


        logger.info(
            "Dynamic Profit Engine v2.0 initialized"
        )



    # ======================================
    # MAIN DECISION
    # ======================================


    def evaluate(

        self,

        position,

        market_state

    ):


        entry = position.entry_price

        price = market_state["price"]


        profit = self.calculate_profit(

            entry,

            price

        )


        expected_move = market_state.get(

            "expected_move",

            10

        )


        trend = market_state.get(

            "trend",

            "UNKNOWN"

        )


        confidence = market_state.get(

            "confidence",

            0

        )


        momentum = market_state.get(

            "momentum",

            0

        )



        #
        # Emergency exit
        #

        if self.market_failure(

            market_state

        ):


            return {


                "action":
                "FULL_EXIT",


                "reason":
                "Trend breakdown"


            }



        #
        # Strong continuation
        #

        if (

            trend == "BULLISH"

            and

            confidence >= 80

            and

            momentum >= 75

        ):


            return {


                "action":
                "HOLD",


                "reason":
                "Strong continuation",


                "profit":
                profit


            }



        #
        # Adaptive levels
        #

        levels = self.generate_levels(

            expected_move

        )



        for level in levels:


            if profit >= level["profit"]:


                return {


                    "action":
                    "PARTIAL_EXIT",


                    "sell_percent":
                    level["sell"],


                    "profit":
                    profit,


                    "target":
                    expected_move


                }



        return {


            "action":
            "HOLD",


            "profit":
            profit

        }



    # ======================================
    # TARGET GENERATOR
    # ======================================


    def generate_levels(

        self,

        expected_move

    ):


        if expected_move <= 5:


            return [

                {
                    "profit":2,
                    "sell":50
                },

                {
                    "profit":5,
                    "sell":50
                }

            ]



        elif expected_move <= 15:


            return [

                {
                    "profit":3,
                    "sell":20
                },

                {
                    "profit":7,
                    "sell":30
                },

                {
                    "profit":expected_move,
                    "sell":30
                }

            ]



        else:


            return [

                {
                    "profit":5,
                    "sell":15
                },

                {
                    "profit":10,
                    "sell":20
                },

                {
                    "profit":20,
                    "sell":30
                },

                {
                    "profit":expected_move,
                    "sell":20
                }

            ]



    # ======================================
    # PROFIT
    # ======================================


    def calculate_profit(

        self,

        entry,

        current

    ):


        return round(

            (

                current-entry

            )

            /

            entry

            *

            100,

            2

        )



    # ======================================
    # MARKET FAILURE
    # ======================================


    def market_failure(

        self,

        market

    ):


        if market.get(
            "trend"
        ) == "BEARISH" and market.get(
            "confidence",
            0
        ) > 75:

            return True



        if market.get(
            "volume_strength",
            100
        ) < 25:

            return True



        return False