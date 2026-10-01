"""
Atlas Fusion Engine v1.0

Professional decision aggregation layer.

Responsibilities:

- Combine intelligence sources
- Normalize scores
- Calculate confidence
- Select action
- Apply safety filters

Pipeline:

Agents
  |
Reasoning
  |
Memory
  |
Fusion
  |
Decision Candidate

"""


from datetime import datetime



from core.decision import (
    DecisionAction
)





class FusionEngine:



    VERSION = "1.0"



    MIN_CONFIDENCE = 0.55





    def __init__(
        self,
        weights=None
    ):


        self.weights = weights or {


            "technical":
                0.40,


            "momentum":
                0.20,


            "risk":
                0.20,


            "macro":
                0.10,


            "sentiment":
                0.10

        }







    # =================================================
    # MAIN FUSION
    # =================================================


    def fuse(

        self,

        agents,

        reasoning,

        memory

    ):



        buy_score = 0.0

        sell_score = 0.0

        hold_score = 0.0





        # =============================================
        # AGENTS
        # =============================================


        for name, data in agents.items():


            weight = self.weights.get(

                name,

                0

            )



            score = float(

                data.get(

                    "score",

                    0.5

                )

            )



            action = data.get(

                "action",

                "HOLD"

            )




            if action == "BUY":


                buy_score += (

                    score *

                    weight

                )




            elif action == "SELL":


                sell_score += (

                    (1-score)

                    *

                    weight

                )




            else:


                hold_score += (

                    0.5 *

                    weight

                )







        # =============================================
        # REASONING BOOST
        # =============================================


        reason_action = reasoning.get(

            "action",

            "HOLD"

        )


        reason_conf = float(

            reasoning.get(

                "confidence",

                0

            )

        )



        reasoning_weight = 0.35





        if reason_action == "BUY":


            buy_score += (

                reason_conf *

                reasoning_weight

            )




        elif reason_action == "SELL":


            sell_score += (

                reason_conf *

                reasoning_weight

            )




        else:


            hold_score += (

                0.5 *

                reasoning_weight

            )







        # =============================================
        # MEMORY
        # =============================================


        memory_effect = float(

            memory.get(

                "effect",

                0

            )

        )



        if memory_effect > 0:


            buy_score += memory_effect

            sell_score += memory_effect



        elif memory_effect < 0:


            hold_score += abs(

                memory_effect

            )







        # =============================================
        # NORMALIZE
        # =============================================


        total = (

            buy_score

            +

            sell_score

            +

            hold_score

        )



        if total == 0:


            return {


                "action":

                "HOLD",


                "confidence":

                0,


                "scores": {}

            }





        scores = {


            "BUY":

            round(

                buy_score / total,

                3

            ),



            "SELL":

            round(

                sell_score / total,

                3

            ),



            "HOLD":

            round(

                hold_score / total,

                3

            )

        }





        winner = max(

            scores,

            key=scores.get

        )



        confidence = scores[winner]







        # =============================================
        # SAFETY FILTER
        # =============================================


        if confidence < self.MIN_CONFIDENCE:


            winner = "HOLD"







        return {


            "action":

            winner,



            "confidence":

            confidence,



            "scores":

            scores,



            "timestamp":

            datetime.now().isoformat()


        }