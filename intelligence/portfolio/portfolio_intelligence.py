from __future__ import annotations

from datetime import datetime, UTC



class PortfolioIntelligence:


    VERSION = "1.0"



    def allocate(

        self,

        opportunities

    ):


        portfolio = {


            "low_risk": [],

            "medium_risk": [],

            "high_risk": []

        }



        for coin in opportunities:


            score = coin.get(
                "score",
                0
            )


            if score >= 80:


                portfolio["low_risk"].append(
                    coin
                )


            elif score >= 60:


                portfolio["medium_risk"].append(
                    coin
                )


            else:


                portfolio["high_risk"].append(
                    coin
                )



        return {


            "portfolio":

                portfolio,


            "time":

                datetime.now(UTC).isoformat()

        }