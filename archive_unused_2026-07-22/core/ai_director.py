"""
Atlas AI Director
Master Decision Coordinator
"""

import logging


logger = logging.getLogger("AtlasAI")


class AIDirector:

    def __init__(self):

        self.weights = {

            "technical": 0.20,
            "market": 0.15,
            "strategy": 0.25,
            "confidence": 0.20,
            "opportunity": 0.10,
            "risk": 0.10

        }

    # =======================================
    # SCORE
    # =======================================

    def calculate_score(self, context):

        technical = context.technical.get(
            "score",
            50
        )

        market = context.market.get(
            "score",
            50
        )

        strategy = context.strategy.get(
            "score",
            50
        )

        confidence = context.confidence

        opportunity = context.opportunity.get(
            "score",
            50
        )

        risk = 100

        if context.risk.get(
            "approved",
            False
        ) is False:

            risk = 25

        score = (

            technical * self.weights["technical"]

            +

            market * self.weights["market"]

            +

            strategy * self.weights["strategy"]

            +

            confidence * self.weights["confidence"]

            +

            opportunity * self.weights["opportunity"]

            +

            risk * self.weights["risk"]

        )

        return round(
            score,
            2
        )

    # =======================================
    # DECISION
    # =======================================

    def decide(self, context):

        score = self.calculate_score(
            context
        )

        decision = "WAIT"

        if score >= 80:
            decision = "BUY"

        elif score <= 30:
            decision = "SELL"

        context.decision = {

            "action": decision,

            "director_score": score,

            "reason": "AI Director Final Decision"

        }

        logger.info(
            f"[DIRECTOR] {decision} ({score})"
        )

        return context.decision