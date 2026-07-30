"""
Atlas AI v6.0
Opportunity Engine

Market Opportunity Detection
Probability + Risk + Strategy Evaluation
"""


class OpportunityEngine:


    def __init__(self):

        self.minimum_trade_score = 60



    def evaluate(
        self,
        regime,
        strategy,
        confidence,
        pattern=None,
        outcome=None
    ):


        score = 0

        reasons = []



        # ==========================
        # MARKET REGIME
        # ==========================


        regime_type = regime.get(
            "regime",
            ""
        )


        regime_conf = regime.get(
            "confidence",
            0
        )


        if regime_type == "STRONG_TREND":

            score += 25

            reasons.append(
                "Güçlü trend"
            )


        elif regime_type == "WEAK_TREND":

            score += 10

            reasons.append(
                "Zayıf trend"
            )


        elif regime_type == "RANGE":

            score += 5

            reasons.append(
                "Yatay piyasa"
            )



        score += min(
            regime_conf / 4,
            25
        )



        # ==========================
        # STRATEGY
        # ==========================


        strategy_score = strategy.get(
            "score",
            0
        )


        if strategy_score >= 75:


            score += 25

            reasons.append(
                "Güçlü strateji"
            )


        elif strategy_score >= 60:


            score += 15

            reasons.append(
                "Orta strateji"
            )



        # ==========================
        # CONFIDENCE
        # ==========================


        if confidence >= 75:


            score += 20

            reasons.append(
                "Yüksek güven"
            )


        elif confidence >= 60:


            score += 10

            reasons.append(
                "Yeterli güven"
            )



        # ==========================
        # PATTERN MEMORY
        # ==========================


        if pattern:


            success = pattern.get(
                "SUCCESS_RATE",
                0
            )


            if success >= 70:

                score += 15

                reasons.append(
                    "Başarılı pattern"
                )



        # ==========================
        # OUTCOME MEMORY
        # ==========================


        if outcome:


            success = outcome.get(
                "success_rate",
                50
            )


            if success >= 70:

                score += 15

                reasons.append(
                    "Geçmiş başarı yüksek"
                )



        # maksimum 100

        score = min(
            round(score),
            100
        )



        # ==========================
        # RATING
        # ==========================


        if score >= 85:


            rating = "HIGH"

            trade_allowed = True



        elif score >= 65:


            rating = "MEDIUM"

            trade_allowed = True



        elif score >= 45:


            rating = "WATCH"

            trade_allowed = False



        else:


            rating = "LOW"

            trade_allowed = False




        return {


            "score":

                score,


            "rating":

                rating,


            "trade_allowed":

                trade_allowed,


            "reasons":

                reasons


        }