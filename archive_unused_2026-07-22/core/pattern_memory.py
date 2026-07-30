"""
Atlas AI Pattern Memory v5.1

Pattern Recognition + Historical Success Memory
"""

import json
import os
from datetime import datetime



class PatternMemory:


    def __init__(self):

        self.file = "pattern_memory.json"

        self.data = []

        self.load()



    def load(self):

        if os.path.exists(self.file):

            try:

                with open(
                    self.file,
                    "r"
                ) as f:

                    self.data = json.load(f)


            except Exception:

                self.data = []



    def save(self):

        with open(
            self.file,
            "w"
        ) as f:

            json.dump(
                self.data,
                f,
                indent=4
            )



    def record(
        self,
        symbol,
        regime,
        strategy,
        decision,
        confidence
    ):


        pattern = {


            "time":
            str(datetime.now()),


            "symbol":
            symbol,


            "regime":
            regime.get(
                "regime",
                "UNKNOWN"
            ),


            "trend":
            regime.get(
                "details",
                {}
            ).get(
                "trend",
                "UNKNOWN"
            ),


            "strategy":
            strategy.get(
                "strategy",
                "UNKNOWN"
            ),


            "decision":
            decision.get(
                "action",
                "BEKLE"
            ),


            "confidence":
            confidence,


            "outcome":
            "UNKNOWN",


            "score":
            0

        }



        self.data.append(
            pattern
        )



        if len(self.data) > 10000:

            self.data = self.data[-10000:]



        self.save()




    def update_outcome(
        self,
        symbol,
        result
    ):


        for item in reversed(self.data):


            if (
                item["symbol"]
                ==
                symbol
                and
                item["outcome"]
                ==
                "UNKNOWN"
            ):


                item["outcome"] = result



                if result == "WIN":

                    item["score"] = 10


                elif result == "LOSS":

                    item["score"] = -10


                else:

                    item["score"] = 0



                break



        self.save()




    def find_similar(
        self,
        regime,
        strategy
    ):


        results = []


        target_regime = regime.get(
            "regime",
            "UNKNOWN"
        )


        target_strategy = strategy.get(
            "strategy",
            "UNKNOWN"
        )



        for item in self.data:


            if (

                item.get("regime")
                ==
                target_regime

                and

                item.get("strategy")
                ==
                target_strategy

            ):


                results.append(
                    item
                )



        return results[-50:]




    def insight(
        self,
        regime,
        strategy
    ):



        matches = self.find_similar(
            regime,
            strategy
        )



        if not matches:


            return {

                "status":
                "NO_PATTERN",

                "count":
                0

            }




        buy = 0
        sell = 0
        wait = 0


        win = 0
        loss = 0



        total_score = 0



        for item in matches:



            decision = item.get(
                "decision"
            )



            if decision == "BUY":

                buy += 1



            elif decision == "SELL":

                sell += 1



            else:

                wait += 1




            if item.get("outcome") == "WIN":

                win += 1



            elif item.get("outcome") == "LOSS":

                loss += 1



            total_score += item.get(
                "score",
                0
            )




        success_rate = 0


        if (
            win + loss
            >
            0
        ):


            success_rate = (

                win /

                (
                    win + loss
                )

            ) * 100





        recommendation = "NEUTRAL"



        if buy > sell:

            recommendation = "BUY"



        elif sell > buy:

            recommendation = "SELL"




        return {


            "status":
            "FOUND",


            "count":
            len(matches),


            "BUY":
            buy,


            "SELL":
            sell,


            "WAIT":
            wait,


            "WIN":
            win,


            "LOSS":
            loss,


            "SUCCESS_RATE":
            round(
                success_rate,
                2
            ),


            "SCORE":
            total_score,


            "RECOMMENDATION":
            recommendation

        }