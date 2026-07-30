"""
Atlas Target Prediction Engine v1.0

Predicts expected price movement.

Outputs:

- expected_profit %
- confidence
- risk level

"""


import logging


logger = logging.getLogger(
    "AtlasAI.TargetPrediction"
)



class TargetPredictionEngine:


    def __init__(self):

        self.version="1.0"


        logger.info(
            "Target Prediction Engine v1.0 initialized"
        )



    # =====================================
    # MAIN PREDICTION
    # =====================================


    def predict(
        self,
        market
    ):


        score=0



        #
        # Trend
        #

        trend = market.get(
            "trend",
            "UNKNOWN"
        )


        if trend=="BULLISH":

            score += 25


        elif trend=="BEARISH":

            score -=25




        #
        # Momentum
        #

        momentum = market.get(
            "momentum",
            50
        )


        score += (

            momentum-50

        )*0.5




        #
        # RSI
        #

        rsi=market.get(
            "rsi",
            50
        )


        if 45 <= rsi <= 65:

            score +=15


        elif rsi >75:

            score -=10



        elif rsi <30:

            score +=5





        #
        # Volume
        #

        volume=market.get(
            "volume_strength",
            50
        )


        score += (

            volume-50

        )*0.4





        #
        # Market regime
        #

        regime=market.get(
            "market_regime",
            "NORMAL"
        )



        if regime=="BULL":

            score+=20


        elif regime=="BEAR":

            score-=20





        #
        # Convert score
        #

        expected_profit = self._profit_from_score(
            score
        )


        confidence = self._confidence(
            score
        )



        risk=self._risk(
            score
        )



        return {


            "expected_profit":

            expected_profit,


            "confidence":

            confidence,


            "risk":

            risk,


            "score":

            round(score,2)

        }





    # =====================================
    # PROFIT MODEL
    # =====================================


    def _profit_from_score(
        self,
        score
    ):


        if score >=80:

            return 30



        if score>=60:

            return 20



        if score>=40:

            return 10



        if score>=20:

            return 5



        return 2





    # =====================================
    # CONFIDENCE
    # =====================================


    def _confidence(
        self,
        score
    ):


        confidence = 50 + (

            score/2

        )


        return max(
            10,
            min(
                95,
                round(
                    confidence,
                    2
                )
            )
        )





    # =====================================
    # RISK
    # =====================================


    def _risk(
        self,
        score
    ):


        if score>=60:

            return "LOW"



        if score>=30:

            return "MEDIUM"



        return "HIGH"