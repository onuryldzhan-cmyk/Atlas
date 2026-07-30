"""
Atlas AI Decision Builder v10.0

Final decision object creator.

Responsibilities:

- Convert intelligence result into Decision
- Attach risk information
- Create metadata
- Standardize output


"""


from __future__ import annotations


from datetime import datetime



from core.decision import (
    Decision,
    DecisionAction
)





class DecisionBuilder:



    VERSION = "10.0"





    def __init__(self):


        print(
            "[DECISION] Decision Builder v10.0 initialized"
        )






    # =====================================================
    # BUILD DECISION
    # =====================================================



    def create(
        self,
        symbol,
        fusion,
        risk,
        reasoning=None,
        memory=None,
        agents=None
    ):



        action = self.convert_action(

            fusion.action

        )





        decision = Decision(


            action=action,


            symbol=symbol,



            confidence=round(

                fusion.confidence * 100,

                2

            ),




            reasoning=(

                "Atlas v10 Intelligence Fusion"

            ),




            risk_level=(

                risk.level

            ),





            strategy=(

                "Atlas_v10_MultiAgent"

            ),






            metadata={



                "fusion":

                    fusion.scores,



                "risk":

                    risk.to_dict(),



                "reasoning":

                    reasoning,



                "memory":

                    memory,



                "agents":

                    agents,



                "timestamp":

                    datetime.now()
                    .isoformat()

            }


        )




        print(

            f"[DECISION] "
            f"{symbol} | "
            f"{decision.action.value} | "
            f"Confidence: "
            f"{decision.confidence}%"

        )



        return decision






    # =====================================================
    # ACTION CONVERTER
    # =====================================================



    def convert_action(
        self,
        action
    ):



        action = action.upper()





        if action == "BUY":


            return DecisionAction.BUY




        if action == "SELL":


            return DecisionAction.SELL




        return DecisionAction.HOLD