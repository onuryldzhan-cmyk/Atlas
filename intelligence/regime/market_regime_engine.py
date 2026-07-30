from __future__ import annotations

from datetime import datetime, UTC



class MarketRegimeEngine:


    VERSION = "1.0"



    def analyze(
        self,
        trend_strength,
        volatility,
        volume_change
    ):


        score = 0
        reasons = []



        if trend_strength > 70:

            score += 30

            reasons.append(
                "Güçlü trend"
            )


        elif trend_strength < 30:

            score -= 10

            reasons.append(
                "Zayıf trend"
            )



        if volatility > 70:

            score += 20

            reasons.append(
                "Yüksek volatilite"
            )


        elif volatility < 30:

            reasons.append(
                "Düşük volatilite"
            )



        if volume_change > 20:

            score += 20

            reasons.append(
                "Artan hacim"
            )



        if score >= 50:

            regime = "BULLISH"


        elif score <= 0:

            regime = "BEARISH"


        elif volatility > 80:

            regime = "HIGH_VOLATILITY"


        else:

            regime = "SIDEWAYS"



        return {

            "regime":
                regime,

            "score":
                score,

            "reasons":
                reasons,

            "time":
                datetime.now(UTC).isoformat()

        }