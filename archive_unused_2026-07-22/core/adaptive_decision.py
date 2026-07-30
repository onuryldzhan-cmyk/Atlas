"""
Atlas AI Adaptive Decision v5.1

Learning Based Decision Adjustment
"""


class AdaptiveDecision:


    def __init__(self):

        self.min_confidence = 60



    def evaluate(
        self,
        decision,
        confidence,
        strategy,
        performance=None
    ):


        action = decision.get(
            "action",
            "BEKLE"
        )


        reason = decision.get(
            "reason",
            ""
        )



        strategy_score = strategy.get(
            "score",
            50
        )



        memory_bonus = 0



        if performance:


            success = performance.get(
                "success_rate",
                50
            )


            if success >= 70:

                memory_bonus += 10


            elif success <= 35:

                memory_bonus -= 15




        final_confidence = (

            confidence
            +
            memory_bonus

        )



        if final_confidence > 100:

            final_confidence = 100



        if final_confidence < 0:

            final_confidence = 0




        # Strategy güven kontrolü

        if strategy_score < 40:

            action = "BEKLE"

            reason = (
                "Strategy score düşük"
            )




        # Confidence kontrolü

        elif final_confidence < self.min_confidence:


            action = "BEKLE"

            reason = (
                "Adaptive confidence düşük"
            )




        # Güçlü öğrenilmiş durum

        elif final_confidence >= 75:


            if action == "BEKLE":


                signal = decision.get(
                    "signal",
                    ""
                )


                if signal in [
                    "BUY",
                    "SELL"
                ]:


                    action = signal


                    reason = (
                        "Memory destekli güçlü sinyal"
                    )




        decision["action"] = action


        decision["confidence"] = round(
            final_confidence,
            2
        )


        decision["adaptive_reason"] = reason



        return decision