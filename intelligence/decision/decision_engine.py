from __future__ import annotations

from datetime import datetime, UTC



class DecisionEngine:


    VERSION = "1.1"



    def decide(

        self,

        opportunity_score,

        strategy_confidence,

        regime

    ):


        decision = "HOLD"

        reason = []



        if regime == "BULLISH":


            if opportunity_score >= 70 and strategy_confidence >= 70:


                decision = "BUY"

                reason.append(
                    "Güçlü fırsat ve strateji uyumu"
                )


            elif opportunity_score >= 50:


                decision = "WATCH"

                reason.append(
                    "İzleme seviyesi"
                )



        elif regime == "BEARISH":


            decision = "SELL"

            reason.append(
                "Piyasa düşüş baskısı"
            )



        else:


            decision = "HOLD"

            reason.append(
                "Belirsiz piyasa"
            )



        return {


            "decision":

                decision,


            "reason":

                reason,


            "time":

                datetime.now(UTC).isoformat()

        }