"""
============================================================
ATLAS AI DECISION ENGINE v7.0
============================================================

Central AI Decision Layer.

Responsibilities:

- Evaluate market opportunities
- Calculate confidence
- Select best opportunity
- Generate BUY / SELL / HOLD decisions
- Produce execution-ready Decision objects
- Attach risk parameters

Flow:

Market Intelligence
        |
Opportunity Ranking
        |
Confidence Engine
        |
Risk Evaluation
        |
Decision Object
        |
Risk Manager
        |
Execution

============================================================
"""


from __future__ import annotations


import logging
from typing import List, Dict, Any


from core.decision import (
    Decision,
    DecisionAction,
    RiskLevel
)



logger = logging.getLogger(
    "AtlasAI.DecisionEngine"
)




class DecisionEngine:


    VERSION = "7.0"



    def __init__(

        self,

        min_confidence: float = 60,

        max_position_size: float = 25

    ):


        self.min_confidence = min_confidence

        self.max_position_size = max_position_size


        self.decisions = 0


        self.buy_signals = 0

        self.hold_signals = 0



        logger.info(

            "Atlas Decision Engine v7.0 initialized"

        )





    # =====================================================
    # MAIN DECISION PIPELINE
    # =====================================================


    def decide(

        self,

        opportunities: List[Dict[str, Any]]

    ) -> Decision:



        if not opportunities:


            self.hold_signals += 1


            return Decision(

                action=DecisionAction.HOLD,

                symbol="UNKNOWN",

                confidence=0,

                reasoning="No market opportunities",

                risk_level=RiskLevel.LOW

            )




        best = self.select_best_opportunity(

            opportunities

        )



        confidence = self.calculate_confidence(

            best

        )



        symbol = best.get(

            "symbol",

            "UNKNOWN"

        )



        price = best.get(

            "price",

            0

        )



        score = best.get(

            "score",

            0

        )



        self.decisions += 1





        # =================================================
        # CONFIDENCE FILTER
        # =================================================


        if confidence < self.min_confidence:


            self.hold_signals += 1



            return Decision(

                action=DecisionAction.HOLD,

                symbol=symbol,

                confidence=confidence,

                reasoning=(

                    "Confidence below trading threshold"

                ),

                risk_level=RiskLevel.LOW,


                strategy="Atlas",


                metadata={


                    "score":

                    score,


                    "price":

                    price

                }

            )







        # =================================================
        # BUY DECISION
        # =================================================


        self.buy_signals += 1



        risk = self.calculate_risk(

            confidence

        )



        size = self.calculate_position_size(

            confidence

        )




        return Decision(

            action=DecisionAction.BUY,

            symbol=symbol,

            confidence=confidence,


            reasoning=(

                "High-consensus market opportunity (consensus, not a win probability)"

            ),


            risk_level=risk,


            strategy=best.get(

                "strategy",

                "MOMENTUM"

            ),



            metadata={


                "score":

                score,


                "price":

                price,


                "position_size_pct":

                size,


                "stop_loss_pct":

                self.calculate_stop_loss(

                    risk

                ),



                "take_profit_pct":

                self.calculate_take_profit(

                    risk

                )

            }

        )







    # =====================================================
    # OPPORTUNITY SELECTION
    # =====================================================


    def select_best_opportunity(

        self,

        opportunities

    ):


        valid = [

            x for x in opportunities

            if isinstance(x, dict)

        ]



        if not valid:

            return {}



        return max(

            valid,

            key=lambda x:

            x.get(

                "score",

                0

            )

        )







    # =====================================================
    # CONFIDENCE ENGINE
    # =====================================================


    def calculate_confidence(

        self,

        opportunity

    ):


        score = opportunity.get(

            "score",

            0

        )


        momentum = opportunity.get(

            "momentum",

            0

        )



        confidence = (

            float(score) * 0.8

            +

            float(momentum) * 0.2

        )



        return round(

            min(

                confidence,

                100

            ),

            2

        )








    # =====================================================
    # RISK ENGINE
    # =====================================================


    def calculate_risk(

        self,

        confidence

    ):


        if confidence >= 85:


            return RiskLevel.LOW



        if confidence >= 70:


            return RiskLevel.MEDIUM



        return RiskLevel.HIGH








    # =====================================================
    # POSITION SIZE
    # =====================================================


    def calculate_position_size(

        self,

        confidence

    ):



        size = confidence / 4



        return round(

            min(

                size,

                self.max_position_size

            ),

            2

        )







    # =====================================================
    # STOP LOSS
    # =====================================================


    def calculate_stop_loss(

        self,

        risk

    ):


        if risk == RiskLevel.LOW:

            return 1.5



        if risk == RiskLevel.MEDIUM:

            return 2.5



        return 4







    # =====================================================
    # TAKE PROFIT
    # =====================================================


    def calculate_take_profit(

        self,

        risk

    ):


        if risk == RiskLevel.LOW:

            return 5



        if risk == RiskLevel.MEDIUM:

            return 7



        return 10







    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "decisions":

            self.decisions,


            "buy_signals":

            self.buy_signals,


            "hold_signals":

            self.hold_signals,


            "min_confidence":

            self.min_confidence

        }