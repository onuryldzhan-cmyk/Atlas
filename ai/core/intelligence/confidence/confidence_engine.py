"""
Atlas AI Confidence Engine v10.1

Professional confidence calculation layer.

Responsibilities:

- Measure intelligence agreement
- Penalize signal conflicts
- Combine agents + reasoning
- Calculate market conviction
- Separate confidence from action

Pipeline:

Agents
   |
   v
Agreement Analysis
   |
   v
Reasoning Influence
   |
   v
Risk Adjustment
   |
   v
Final Confidence


"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List



# =====================================================
# CONFIDENCE RESULT MODEL
# =====================================================


@dataclass
class ConfidenceResult:

    value: float

    agreement: float

    reasoning_effect: float

    risk_penalty: float

    explanation: str



    def percentage(self):

        return round(
            self.value * 100,
            2
        )





# =====================================================
# CONFIDENCE ENGINE
# =====================================================


class ConfidenceEngine:


    """
    Atlas Intelligence Confidence Engine v10.1

    Calculates confidence independently
    from decision making.

    """


    VERSION = "10.1"



    def __init__(self):


        print(
            "[CONFIDENCE] Confidence Engine v10.1 initialized"
        )




    # =================================================
    # MAIN CALCULATOR
    # =================================================


    def calculate(

        self,
        agents: Dict,
        reasoning: Dict,
        risk: Dict | None = None

    ) -> ConfidenceResult:



        agreement = self.calculate_agent_agreement(

            agents

        )



        reasoning_effect = self.calculate_reasoning_effect(

            reasoning

        )



        risk_penalty = self.calculate_risk_penalty(

            risk

        )



        confidence = (

            agreement * 0.50

            +

            reasoning_effect * 0.35

            -

            risk_penalty * 0.15

        )



        confidence = max(

            0,

            min(

                confidence,

                1

            )

        )




        explanation = (

            f"Agreement={agreement:.2f} "

            f"Reasoning={reasoning_effect:.2f} "

            f"RiskPenalty={risk_penalty:.2f}"

        )




        return ConfidenceResult(

            value=confidence,

            agreement=agreement,

            reasoning_effect=reasoning_effect,

            risk_penalty=risk_penalty,

            explanation=explanation

        )





    # =================================================
    # AGENT AGREEMENT
    # =================================================


    def calculate_agent_agreement(

        self,

        agents: Dict

    ):


        if not agents:


            return 0



        actions = []



        for data in agents.values():


            actions.append(

                data.get(

                    "action",

                    "HOLD"

                )

            )



        if not actions:


            return 0




        counts = {}



        for action in actions:


            counts[action] = (

                counts.get(

                    action,

                    0

                )

                + 1

            )



        strongest = max(

            counts.values()

        )



        return strongest / len(actions)





    # =================================================
    # REASONING EFFECT
    # =================================================


    def calculate_reasoning_effect(

        self,

        reasoning: Dict

    ):



        confidence = reasoning.get(

            "confidence",

            0

        )



        confidence = float(

            confidence

        )



        if confidence > 1:


            confidence = confidence / 100



        return max(

            0,

            min(

                confidence,

                1

            )

        )






    # =================================================
    # RISK PENALTY
    # =================================================


    def calculate_risk_penalty(

        self,

        risk

    ):



        if not risk:


            return 0



        level = risk.get(

            "level",

            "MEDIUM"

        )



        penalties = {


            "LOW":

                0.05,


            "MEDIUM":

                0.20,


            "HIGH":

                0.40


        }



        return penalties.get(

            level,

            0.20

        )





    # =================================================
    # DEBUG
    # =================================================


    def explain(

        self,

        result: ConfidenceResult

    ):



        return {


            "confidence":

                result.percentage(),


            "agreement":

                round(

                    result.agreement,

                    2

                ),


            "reasoning":

                round(

                    result.reasoning_effect,

                    2

                ),


            "risk_penalty":

                round(

                    result.risk_penalty,

                    2

                ),


            "explanation":

                result.explanation

        }