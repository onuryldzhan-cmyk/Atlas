from __future__ import annotations

from datetime import datetime, UTC



class StrategySelector:


    VERSION = "1.0"



    def select(

        self,

        regime,

        opportunity_score,

        volatility

    ):


        strategy = "HOLD"

        confidence = 0

        reasons = []



        if regime == "BULLISH":


            if opportunity_score >= 80:


                strategy = "TREND_FOLLOWING"

                confidence = 85

                reasons.append(
                    "Güçlü yükseliş ortamı"
                )



            elif opportunity_score >= 60:


                strategy = "MOMENTUM"

                confidence = 70

                reasons.append(
                    "Pozitif momentum"
                )



        elif regime == "SIDEWAYS":


            strategy = "MEAN_REVERSION"

            confidence = 60

            reasons.append(
                "Yatay piyasa"
            )



        elif regime == "HIGH_VOLATILITY":


            strategy = "SCALPING"

            confidence = 55

            reasons.append(
                "Yüksek volatilite"
            )



        elif regime == "BEARISH":


            strategy = "DEFENSIVE"

            confidence = 70

            reasons.append(
                "Düşüş riski"
            )



        return {


            "strategy":

                strategy,


            "confidence":

                confidence,


            "reasons":

                reasons,


            "time":

                datetime.now(UTC).isoformat()

        }