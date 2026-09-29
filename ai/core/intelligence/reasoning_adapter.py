"""
Atlas AI Reasoning Adapter v10.0

Bridge between Atlas Brain and Reasoning Engine.

Responsibilities:

- Prepare reasoning input
- Execute deep analysis
- Normalize output
- Protect brain from reasoning errors


"""


from __future__ import annotations



from typing import Dict

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)





class ReasoningAdapter:



    VERSION = "10.0"





    def __init__(
        self,
        reasoning_engine=None
    ):


        self.engine = reasoning_engine



        _log.debug(
            "[REASONING] Reasoning Adapter v10.0 initialized"
        )






    # =====================================================
    # MAIN REASONING
    # =====================================================


    def analyze(
        self,
        symbol: str,
        market_data: Dict
    ):


        if not self.engine:


            return {


                "action":
                    "HOLD",


                "confidence":
                    0


            }






        technical = {



            "rsi":

                market_data.get(
                    "rsi",
                    50
                ),



            "trend":

                market_data.get(
                    "trend",
                    "SIDEWAYS"
                ),



            "macd":

                market_data.get(
                    "macd",
                    0
                )

        }





        macro = {



            "fed_policy":

                market_data.get(
                    "fed_policy",
                    "neutral"
                ),



            "inflation":

                market_data.get(
                    "inflation",
                    2
                )

        }





        sentiment = {



            "fear_greed":

                market_data.get(
                    "fear_greed",
                    50
                )

        }





        try:



            result = self.engine.analyze_market(

                symbol,

                technical,

                macro,

                sentiment

            )





            action = (


                result.decision_type
                .value
                .upper()


            )





            confidence = float(

                result.confidence

            )






        except Exception as e:



            _log.debug(

                f"[REASONING ERROR] {e}"

            )



            action="HOLD"


            confidence=0







        _log.debug(

            f"[REASONING] "
            f"{symbol} -> "
            f"{action} "
            f"confidence={confidence:.2f}"

        )





        return {



            "action":

                action,



            "confidence":

                confidence

        }