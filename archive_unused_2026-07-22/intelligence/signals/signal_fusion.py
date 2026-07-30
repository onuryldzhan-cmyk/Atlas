class SignalFusion:


    def __init__(self):

        self.name = "Atlas Signal Fusion v1"



    def combine(
        self,
        technical,
        market,
        risk
    ):


        score = 50

        reasons = []



        # Technical ağırlık %40

        technical_score = (
            technical["confidence"] - 50
        ) * 0.4


        score += technical_score


        reasons.append(

            f"Technical {technical['signal']}"

        )



        # Market ağırlık %40

        market_score = (

            market["confidence"] - 50

        ) * 0.4


        score += market_score


        reasons.append(

            f"Market {market['signal']}"

        )



        # Risk ağırlık %20

        risk_score = (

            risk["confidence"] - 50

        ) * 0.2


        score += risk_score


        reasons.append(

            f"Risk {risk['signal']}"

        )



        score = max(

            0,

            min(

                score,

                100

            )

        )



        if score >= 65:

            decision = "BUY"


        elif score <= 35:

            decision = "SELL"


        else:

            decision = "HOLD"



        return {


            "decision": decision,


            "confidence": round(

                score,

                2

            ),


            "reasons": reasons


        }