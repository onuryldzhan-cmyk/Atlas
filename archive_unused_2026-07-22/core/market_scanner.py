"""
Atlas AI v6.0
Market Scanner Engine

Daily Opportunity Discovery System
"""


import logging


logger = logging.getLogger("AtlasAI")



class MarketScanner:


    def __init__(
        self,
        brain=None
    ):

        self.brain = brain


        self.watchlist = [

            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "AVAXUSDT",
            "LINKUSDT",
            "DOGEUSDT",
            "DOTUSDT"

        ]



    def calculate_score(
        self,
        data
    ):


        score = 0


        decision = data.get(
            "decision",
            {}
        )


        confidence = decision.get(
            "confidence",
            0
        )


        action = decision.get(
            "action",
            "BEKLE"
        )



        opportunity = decision.get(
            "opportunity",
            {}
        )


        opportunity_score = opportunity.get(
            "score",
            0
        )



        if action in [
            "BUY",
            "SELL"
        ]:

            score += 30



        if confidence >= 70:

            score += 30


        elif confidence >= 60:

            score += 20



        score += opportunity_score / 2



        return round(
            score,
            2
        )




    def scan(
        self
    ):


        if not self.brain:

            return []



        logger.info(
            "Atlas Market Scanner başladı."
        )



        results = []



        analysis = self.brain.run(
            self.watchlist
        )



        for symbol,data in analysis.items():


            score = self.calculate_score(
                data
            )


            results.append(

                {

                    "symbol":
                        symbol,


                    "score":
                        score,


                    "decision":
                        data.get(
                            "decision",
                            {}
                        )

                }

            )



        results.sort(

            key=lambda x:
                x["score"],

            reverse=True

        )



        return results[:5]



    def print_report(
        self,
        results
    ):


        print("\n")
        print("==============================")
        print(" ATLAS MARKET OPPORTUNITIES ")
        print("==============================")


        for item in results:


            decision = item["decision"]


            print(

                f"""
{item['symbol']}

Score:
{item['score']}

Action:
{decision.get('action')}

Confidence:
%{decision.get('confidence')}

"""

            )


        print("==============================")