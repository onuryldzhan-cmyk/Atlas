"""
Atlas Opportunity Engine v2.0

Institutional opportunity ranking system.

Analyzes:

- Reward
- Risk
- Trend
- Momentum
- Liquidity

"""


import logging


logger = logging.getLogger(
    "AtlasAI.Opportunity"
)



class OpportunityEngine:


    def __init__(self):


        self.version="2.0"


        logger.info(
            "Opportunity Engine v2.0 initialized"
        )



    # ====================================
    # MAIN ANALYSIS
    # ====================================


    def analyze(

        self,

        symbol,

        market

    ):


        trend = market.get(
            "trend",
            "UNKNOWN"
        )


        momentum = market.get(
            "momentum",
            0
        )


        volume = market.get(
            "volume_strength",
            0
        )


        volatility = market.get(
            "volatility",
            "MEDIUM"
        )


        reward = self._calculate_reward(
            market
        )


        risk = self._calculate_risk(
            market
        )



        score = (

            trend_score(trend) * 0.30

            +

            momentum * 0.20

            +

            volume * 0.15

            +

            risk * 0.20

            +

            reward * 0.15

        )



        return {


            "symbol":
            symbol,


            "score":
            round(score,2),


            "risk":
            self._risk_label(
                risk
            ),


            "expected_reward":
            reward,


            "decision":
            self._decision(score)

        }




    # ====================================
    # REWARD
    # ====================================


    def _calculate_reward(

        self,

        market

    ):


        target = market.get(
            "target_price"
        )


        price = market.get(
            "price"
        )


        if not target or not price:

            return 0



        return round(

            ((target-price)/price)*100,

            2

        )




    # ====================================
    # RISK
    # ====================================


    def _calculate_risk(

        self,

        market

    ):


        score=100



        if market.get(
            "volatility"
        )=="HIGH":

            score-=30



        if market.get(
            "trend"
        )=="BEARISH":

            score-=40



        return max(
            score,
            0
        )




    # ====================================
    # LABEL
    # ====================================


    def _risk_label(

        self,

        score

    ):


        if score>=75:

            return "LOW"



        if score>=45:

            return "MEDIUM"



        return "HIGH"




    def _decision(

        self,

        score

    ):


        if score>=75:

            return "BUY"



        if score>=55:

            return "WATCH"



        return "IGNORE"





def trend_score(
    trend
):


    if trend=="BULLISH":

        return 100


    if trend=="SIDEWAYS":

        return 50


    return 20