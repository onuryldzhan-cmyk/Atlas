"""
Atlas AI Signal Fusion Engine v5.1

Hedge Fund Adaptive Multi Factor Decision Layer
"""


class SignalFusion:


    def fuse(
        self,
        tech: dict,
        market: dict
    ) -> dict:


        score = 50

        reasons = []


        rsi = tech.get(
            "rsi",
            50
        )

        trend = tech.get(
            "trend",
            "NEUTRAL"
        )

        momentum = tech.get(
            "momentum",
            0
        )

        volume = tech.get(
            "volume_signal",
            "NEUTRAL"
        )

        adx = tech.get(
            "adx",
            0
        )

        sentiment = market.get(
            "sentiment",
            "Nötr"
        )

        volatility = market.get(
            "volatility",
            0
        )


        # ======================
        # TREND QUALITY
        # ======================


        if trend in [
            "BULLISH",
            "UPTREND",
            "YUKARI"
        ]:

            score += 25

            reasons.append(
                "Yükseliş trendi"
            )


        elif trend in [
            "BEARISH",
            "DOWNTREND",
            "AŞAĞI"
        ]:

            score -= 25

            reasons.append(
                "Düşüş trendi"
            )



        # ======================
        # ADX TREND POWER
        # ======================


        if adx >= 25:

            score += 10

            reasons.append(
                "Güçlü trend kalitesi"
            )


        elif adx < 15:

            score -= 10

            reasons.append(
                "Zayıf trend"
            )



        # ======================
        # RSI
        # ======================


        if rsi < 30:

            score += 12

            reasons.append(
                "Aşırı satım fırsatı"
            )


        elif rsi > 70:

            score -= 8

            reasons.append(
                "Aşırı alım riski"
            )



        # ======================
        # MOMENTUM
        # ======================


        if momentum > 0:

            score += 8

            reasons.append(
                "Pozitif momentum"
            )


        elif momentum < 0:

            score -= 8

            reasons.append(
                "Negatif momentum"
            )



        # ======================
        # VOLUME
        # ======================


        if volume == "HIGH":

            score += 8

            reasons.append(
                "Hacim desteği"
            )



        # ======================
        # MARKET SENTIMENT
        # ======================


        if sentiment == "Pozitif":

            score += 10

            reasons.append(
                "Pozitif piyasa"
            )


        elif sentiment == "Negatif":

            score -= 15

            reasons.append(
                "Negatif piyasa baskısı"
            )



        # ======================
        # VOLATILITY CONTROL
        # ======================


        if volatility > 0.02:

            score -= 10

            reasons.append(
                "Yüksek volatilite"
            )



        score = max(
            0,
            min(
                100,
                score
            )
        )



        # ======================
        # FINAL SIGNAL
        # ======================


        if score >= 65:

            signal = "AL"


        elif score <= 35:

            signal = "SAT"


        else:

            signal = "BEKLE"



        # ======================
        # STRENGTH
        # ======================


        if score >= 85:

            strength = "ELITE"


        elif score >= 65:

            strength = "STRONG"


        elif score >= 45:

            strength = "NEUTRAL"


        else:

            strength = "WEAK"



        return {

            "signal": signal,

            "score": score,

            "strength": strength,

            "reasons": reasons,

            "technical": tech,

            "market": market

        }