"""
Atlas AI Market Regime Engine v1

Market condition classification system
"""


class MarketRegime:


    def __init__(self):

        self.regimes = [

            "STRONG_TREND",
            "WEAK_TREND",
            "RANGE",
            "HIGH_VOLATILITY",
            "CRASH",
            "RECOVERY"

        ]



    def detect(
        self,
        technical,
        market
    ):


        trend = technical.get(
            "trend",
            "NEUTRAL"
        )


        adx = technical.get(
            "adx",
            0
        )


        rsi = technical.get(
            "rsi",
            50
        )


        volatility = market.get(
            "volatility",
            0
        )



        regime = "RANGE"


        confidence = 50



        # ==============================
        # CRASH DETECTION
        # ==============================


        if (

            trend == "BEARISH"

            and

            rsi < 25

            and

            volatility > 0.03

        ):


            regime = "CRASH"

            confidence = 90



        # ==============================
        # HIGH VOLATILITY
        # ==============================


        elif volatility > 0.03:


            regime = "HIGH_VOLATILITY"

            confidence = 80



        # ==============================
        # STRONG TREND
        # ==============================


        elif adx >= 40:


            regime = "STRONG_TREND"

            confidence = min(
                90,
                50 + adx
            )



        # ==============================
        # WEAK TREND
        # ==============================


        elif adx >= 20:


            regime = "WEAK_TREND"

            confidence = 65



        # ==============================
        # RECOVERY
        # ==============================


        if (

            trend == "BULLISH"

            and

            rsi < 45

            and

            adx > 15

        ):


            regime = "RECOVERY"

            confidence = 70




        return {


            "regime": regime,


            "confidence": round(
                confidence,
                2
            ),


            "details": {


                "trend": trend,

                "adx": adx,

                "rsi": rsi,

                "volatility": volatility

            }

        }