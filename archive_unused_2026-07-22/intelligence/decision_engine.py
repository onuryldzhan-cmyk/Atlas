"""
Atlas AI Decision Engine v10

Adaptive Hedge Fund Decision Layer
"""


class DecisionEngine:


    def __init__(self):

        self.buy_threshold = 60

        self.sell_threshold = 40

        self.minimum_confidence = 65




    def decide(
        self,
        fusion,
        confidence
    ):


        if not isinstance(fusion, dict):

            return {
                "action": "BEKLE",
                "reason": "Fusion verisi yok"
            }



        signal = fusion.get(
            "signal",
            "BEKLE"
        )


        score = fusion.get(
            "score",
            50
        )


        strength = fusion.get(
            "strength",
            "NEUTRAL"
        )


        reasons = fusion.get(
            "reasons",
            []
        )



        signal_strength = score - 50




        if confidence < self.minimum_confidence:

            return {

                "action": "BEKLE",

                "reason":
                "Confidence düşük",

                "confidence":
                confidence

            }





        # BUY LOGIC

        if (

            signal == "AL"

            and score >= self.buy_threshold

            and strength in [
                "STRONG",
                "VERY_STRONG"
            ]

        ):


            return {

                "action":
                "BUY",

                "reason":
                " | ".join(reasons),

                "strength":
                strength,

                "signal_strength":
                signal_strength,

                "confidence":
                confidence

            }




        # SELL LOGIC

        if (

            signal == "SAT"

            and score <= self.sell_threshold

            and strength in [
                "STRONG",
                "VERY_STRONG"
            ]

        ):


            return {

                "action":
                "SELL",

                "reason":
                " | ".join(reasons),

                "strength":
                strength,

                "signal_strength":
                signal_strength,

                "confidence":
                confidence

            }




        return {

            "action":
            "BEKLE",

            "reason":
            "Sinyal şartları tamamlanmadı",

            "strength":
            strength,

            "signal_strength":
            signal_strength,

            "confidence":
            confidence

        }