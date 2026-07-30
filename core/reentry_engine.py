"""
Atlas ReEntry Engine v1.0

Professional re-entry system.

Features
--------

- Detect new opportunities after exits
- Trend confirmation
- Momentum confirmation
- Confidence filtering
- Prevent emotional re-buy

"""


import logging


logger = logging.getLogger(
    "AtlasAI.ReEntry"
)




class ReEntryEngine:


    def __init__(self):


        self.version = "1.0"


        logger.info(
            "ReEntry Engine v1.0 initialized"
        )



    # =====================================================
    # EVALUATE
    # =====================================================


    def evaluate(

        self,

        symbol,

        market,

        previous_position

    ):


        """

        Decide:

        REENTER
        WAIT


        """


        if not previous_position:


            return {


                "action":
                "WAIT",

                "reason":
                "No previous position"

            }




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

            0

        )


        volume = market.get(

            "volume_strength",

            0

        )



        #
        # Trend check
        #

        if trend != "BULLISH":


            return {


                "action":
                "WAIT",


                "reason":
                "Trend not confirmed"

            }





        #
        # Confidence check
        #

        if confidence < 75:


            return {


                "action":
                "WAIT",


                "reason":
                "Low confidence"

            }




        #
        # Momentum check
        #

        if momentum < 70:


            return {


                "action":
                "WAIT",


                "reason":
                "Weak momentum"

            }




        #
        # Volume check
        #

        if volume < 50:


            return {


                "action":
                "WAIT",


                "reason":
                "Weak volume"

            }




        return {


            "action":
            "REENTER",


            "symbol":
            symbol,


            "confidence":
            confidence,


            "reason":
            "Trend continuation confirmed"


        }