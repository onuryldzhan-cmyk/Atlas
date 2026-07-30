"""
Atlas Decision Builder v1.0

Decision object factory.

Responsibilities:

- Convert fusion output into Decision
- Attach metadata
- Standardize output format

"""


from datetime import datetime


from core.decision import (
    Decision,
    DecisionAction
)





class DecisionBuilder:



    VERSION = "1.0"






    def build(

        self,

        symbol,

        fusion_result,

        risk_level

    ):



        action_name = fusion_result.get(

            "action",

            "HOLD"

        )






        if action_name == "BUY":


            action = DecisionAction.BUY




        elif action_name == "SELL":


            action = DecisionAction.SELL




        else:


            action = DecisionAction.HOLD






        confidence = float(

            fusion_result.get(

                "confidence",

                0

            )

        )





        decision = Decision(



            action=action,



            symbol=symbol,



            confidence=round(

                confidence * 100,

                2

            ),



            reasoning=(

                "Atlas Intelligence Fusion"

            ),



            risk_level=risk_level,



            strategy=(

                "Atlas_v9_MultiAgent"

            ),




            metadata={



                "fusion":

                fusion_result,



                "timestamp":

                datetime.now().isoformat()



            }



        )




        return decision