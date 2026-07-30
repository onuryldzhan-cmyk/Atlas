"""
Atlas Position Re-entry Engine v1.0

Professional re-entry system.

Features
--------
- Detect renewed opportunities
- Buy back after profit taking
- Prevent emotional re-entry
- Confidence based decisions
"""


import logging


logger = logging.getLogger(
    "AtlasAI.ReEntry"
)



class PositionReEntryEngine:


    def __init__(self):

        self.version = "1.0"


        logger.info(
            "Position Re-entry Engine v1.0 initialized"
        )



    # ==================================================
    # RE-ENTRY DECISION
    # ==================================================


    def evaluate(

        self,

        position,

        market_state

    ):


        """
        Returns:

        RE_ENTER

        WAIT

        IGNORE

        """



        if not position:


            return {

                "action":
                "IGNORE",

                "reason":
                "No previous position"

            }




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


        volume = market_state.get(

            "volume_strength",

            0

        )




        # ==========================
        # ENTRY CONDITIONS
        # ==========================


        if (

            trend == "BULLISH"

            and

            confidence >= 75

            and

            momentum >= 70

            and

            volume >= 60

        ):


            logger.info(

                "[REENTRY] Opportunity detected"

            )


            return {


                "action":

                "RE_ENTER",


                "confidence":

                confidence,


                "reason":

                "Trend continuation"

            }




        return {


            "action":

            "WAIT",


            "reason":

            "Conditions not ready"

        }