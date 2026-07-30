"""
Atlas AI Opportunity Scanner v4.4
Multi Asset Opportunity Ranking Engine
"""


class OpportunityScanner:


    def __init__(self):

        self.minimum_confidence = 60



    def scan(
        self,
        analysis_results
    ):


        opportunities = []



        for symbol,data in analysis_results.items():


            decision = data.get(
                "decision",
                {}
            )


            confidence = data.get(
                "confidence",
                0
            )


            action = decision.get(
                "action",
                "BEKLE"
            )



            strategy = data.get(
                "strategy",
                {}
            )



            score = strategy.get(
                "score",
                0
            )



            if action in [
                "BUY",
                "SELL"
            ] and confidence >= self.minimum_confidence:



                opportunities.append(

                    {

                        "symbol": symbol,

                        "action": action,

                        "confidence": confidence,

                        "strategy": strategy.get(
                            "strategy",
                            "NONE"
                        ),

                        "score": score,

                        "reason": decision.get(
                            "reason",
                            ""
                        )

                    }

                )




        opportunities.sort(

            key=lambda x:

                (

                    x["confidence"],

                    x["score"]

                ),

            reverse=True

        )




        return opportunities





    def best(
        self,
        analysis_results
    ):


        opportunities = self.scan(
            analysis_results
        )



        if not opportunities:

            return None



        return opportunities[0]





    def report(
        self,
        analysis_results
    ):


        opportunities = self.scan(
            analysis_results
        )



        print(
            "\n===== ATLAS OPPORTUNITY SCANNER ====="
        )



        if not opportunities:


            print(
                "Şu an uygun fırsat bulunamadı."
            )


        else:


            for item in opportunities:


                print(

                    f"{item['symbol']} | "
                    f"{item['action']} | "
                    f"Confidence: %{item['confidence']} | "
                    f"Strategy: {item['strategy']}"

                )



        print(
            "====================================\n"
        )



        return opportunities