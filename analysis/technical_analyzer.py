"""
Atlas Technical Analyzer v5.2

Real market technical intelligence.
"""


import logging
from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.TechnicalAnalyzer"
)




class TechnicalAnalyzer:


    VERSION = "5.2"



    def __init__(
        self
    ):

        logger.info(
            "Atlas Technical Analyzer v5.2 initialized"
        )




    # ==========================
    # EMA
    # ==========================


    def ema(
        self,
        prices,
        period
    ):


        if len(prices) < period:

            return None



        multiplier = (
            2 /
            (period + 1)
        )


        ema = prices[0]


        for price in prices[1:]:

            ema = (
                price - ema
            ) * multiplier + ema



        return round(
            ema,
            4
        )





    # ==========================
    # RSI
    # ==========================


    def rsi(
        self,
        prices,
        period=14
    ):


        if len(prices) <= period:

            return None



        gains = []

        losses = []



        for i in range(
            1,
            len(prices)
        ):

            diff = (
                prices[i]
                -
                prices[i-1]
            )


            if diff >= 0:

                gains.append(diff)

                losses.append(0)


            else:

                gains.append(0)

                losses.append(
                    abs(diff)
                )



        avg_gain = sum(
            gains[-period:]
        ) / period


        avg_loss = sum(
            losses[-period:]
        ) / period



        if avg_loss == 0:

            return 100



        rs = (
            avg_gain /
            avg_loss
        )


        return round(
            100 -
            (
                100 /
                (1+rs)
            ),
            2
        )





    # ==========================
    # ANALYZE
    # ==========================


    def analyze(
        self,
        candles
    ):


        closes = [

            c["close"]

            for c in candles

        ]



        ema20 = self.ema(
            closes,
            20
        )


        ema50 = self.ema(
            closes,
            50
        )


        rsi = self.rsi(
            closes
        )



        score = 50

        reasons=[]



        if ema20 and ema50:


            if ema20 > ema50:

                score += 20

                reasons.append(
                    "EMA20 above EMA50"
                )

            else:

                score -= 20

                reasons.append(
                    "EMA20 below EMA50"
                )




        if rsi:


            if rsi < 30:

                score += 10

                reasons.append(
                    "Oversold"
                )


            elif rsi > 70:

                score -= 10

                reasons.append(
                    "Overbought"
                )





        score = max(
            0,
            min(
                100,
                score
            )
        )



        return {

            "score":
            score,


            "ema20":
            ema20,


            "ema50":
            ema50,


            "rsi":
            rsi,


            "reasons":
            reasons,


            "time":
            datetime.now(
                UTC
            ).isoformat()

        }