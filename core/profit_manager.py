"""
Atlas Adaptive Profit Manager v2.0

Dynamic profit taking engine.

Features:
- AI target based exits
- Dynamic partial selling
- Trend continuation protection
- Emergency exit
- Trailing protection
"""


import logging


logger = logging.getLogger(
    "AtlasAI.ProfitManager"
)



class ProfitManager:


    def __init__(self):


        self.version = "2.0"


        logger.info(
            "Adaptive Profit Manager v2.0 initialized"
        )



    # ==========================================
    # MAIN EVALUATION
    # ==========================================


    def evaluate(
        self,
        position,
        market
    ):


        entry = position.get(
            "entry_price"
        )


        price = market.get(
            "price"
        )


        if not entry or not price:

            return {

                "action":"HOLD"

            }



        profit = (

            (price-entry)

            /

            entry

        ) * 100



        target = market.get(

            "target_profit",

            10

        )



        trend = market.get(

            "trend",

            "UNKNOWN"

        )



        confidence = market.get(

            "confidence",

            0

        )



        # ==================================
        # EMERGENCY EXIT
        # ==================================


        if (

            trend == "BEARISH"

            and

            confidence > 80

            and

            profit > 0

        ):


            return {


                "action":

                "FULL_EXIT",


                "reason":

                "Strong reversal detected"

            }




        # ==================================
        # TRAILING HOLD
        # ==================================


        if (

            trend=="BULLISH"

            and

            confidence > 75

            and

            profit < target

        ):


            return {


                "action":

                "HOLD",


                "reason":

                "Trend continuation"

            }




        # ==================================
        # DYNAMIC PARTIAL EXIT
        # ==================================


        if profit >= target*0.25:


            return {


                "action":

                "PARTIAL_EXIT",


                "sell_percent":

                20,


                "profit":

                round(profit,2)

            }




        if profit >= target*0.50:


            return {


                "action":

                "PARTIAL_EXIT",


                "sell_percent":

                30,


                "profit":

                round(profit,2)

            }




        if profit >= target*0.75:


            return {


                "action":

                "PARTIAL_EXIT",


                "sell_percent":

                30,


                "profit":

                round(profit,2)

            }




        if profit >= target:


            return {


                "action":

                "PARTIAL_EXIT",


                "sell_percent":

                20,


                "profit":

                round(profit,2)

            }




        return {


            "action":

            "HOLD",


            "profit":

            round(profit,2)

        }