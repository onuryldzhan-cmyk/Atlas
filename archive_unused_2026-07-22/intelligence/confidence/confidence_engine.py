"""
Atlas AI Confidence Engine v11

Adaptive Market Confidence Intelligence
"""


class ConfidenceEngine:


    def __init__(self):

        self.weights = {

            "market": 0.25,

            "strategy": 0.20,

            "signal": 0.20,

            "memory": 0.10,

            "trend": 0.10,

            "momentum": 0.10,

            "volatility": 0.05

        }



    def calculate(
        self,
        market_score,
        strategy_confidence,
        signal_strength,
        memory_score,
        risk_level,
        technical=None,
        market=None
    ):


        confidence = 0


        # =========================
        # CORE SCORES
        # =========================


        confidence += (
            market_score *
            self.weights["market"]
        )


        confidence += (
            strategy_confidence *
            self.weights["strategy"]
        )


        confidence += (
            signal_strength *
            self.weights["signal"]
        )


        confidence += (
            memory_score *
            self.weights["memory"]
        )



        # =========================
        # TECHNICAL ANALYSIS
        # =========================


        if technical:

            trend = technical.get(
                "trend",
                ""
            )


            rsi = technical.get(
                "rsi",
                50
            )


            adx = technical.get(
                "adx",
                0
            )



            if trend == "BULLISH":

                confidence += 10 * self.weights["trend"]



            elif trend == "BEARISH":

                confidence += 5 * self.weights["trend"]



            if 45 <= rsi <= 65:

                confidence += 10 * self.weights["momentum"]



            if adx >= 20:

                confidence += 10 * self.weights["momentum"]



        # =========================
        # MARKET CONDITION
        # =========================


        if market:


            sentiment = market.get(
                "sentiment",
                ""
            )


            volatility = market.get(
                "volatility",
                0
            )



            if sentiment == "Pozitif":

                confidence += 10



            elif sentiment == "Negatif":

                confidence -= 10



            if volatility > 0.05:

                confidence -= 10


            elif volatility < 0.01:

                confidence += 5



        # =========================
        # RISK FILTER
        # =========================


        if risk_level == "LOW":

            confidence += 5



        elif risk_level == "MEDIUM":

            confidence -= 5



        elif risk_level == "HIGH":

            confidence -= 15



        confidence = max(
            0,
            min(
                confidence,
                100
            )
        )



        return round(
            confidence,
            2
        )