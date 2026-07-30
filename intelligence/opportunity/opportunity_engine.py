from __future__ import annotations

from datetime import datetime, UTC


class OpportunityEngine:

    VERSION = "1.0"


    def __init__(self):

        self.opportunities = []



    def evaluate(
        self,
        coin_data
    ):

        score = 0

        reasons = []


        change = coin_data.get(
            "change",
            0
        )

        volume = coin_data.get(
            "volume",
            0
        )

        scanner_score = coin_data.get(
            "score",
            0
        )


        score += scanner_score



        if change > 0:

            score += 10

            reasons.append(
                "Pozitif momentum"
            )



        if abs(change) > 3:

            score += 10

            reasons.append(
                "Yüksek hareketlilik"
            )



        if volume > 1000000:

            score += 10

            reasons.append(
                "Yüksek likidite"
            )



        if score >= 80:

            opportunity = "STRONG"

        elif score >= 60:

            opportunity = "GOOD"

        elif score >= 40:

            opportunity = "WEAK"

        else:

            opportunity = "NONE"



        result = {

            "symbol":
                coin_data["symbol"],

            "opportunity":
                opportunity,

            "score":
                score,

            "reasons":
                reasons,

            "time":
                datetime.now(UTC).isoformat()

        }


        self.opportunities.append(
            result
        )


        return result



    def rank(self):

        return sorted(

            self.opportunities,

            key=lambda x:
                x["score"],

            reverse=True

        )