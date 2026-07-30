import json
import os
from datetime import datetime



class PerformanceTracker:


    def __init__(self):

        self.file = "performance.json"


        if not os.path.exists(self.file):

            self.data = {

                "trades": 0,

                "wins": 0,

                "losses": 0,

                "profit": 0,

                "best_trade": None,

                "worst_trade": None,

                "history": []

            }


            self.save()


        else:

            self.load()



    def load(self):

        with open(
            self.file,
            "r"
        ) as f:

            self.data = json.load(f)




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




    def add_trade(
        self,
        symbol,
        result,
        profit
    ):


        self.data["trades"] += 1



        self.data["profit"] += profit



        trade = {

            "symbol": symbol,

            "result": result,

            "profit": profit,

            "time": str(datetime.now())

        }



        self.data["history"].append(
            trade
        )



        if result == "WIN":

            self.data["wins"] += 1


        else:

            self.data["losses"] += 1




        if self.data["best_trade"] is None or profit > self.data["best_trade"]["profit"]:

            self.data["best_trade"] = trade




        if self.data["worst_trade"] is None or profit < self.data["worst_trade"]["profit"]:

            self.data["worst_trade"] = trade



        self.save()



        return self.report()




    def report(self):


        total = self.data["trades"]


        if total > 0:

            winrate = (
                self.data["wins"] / total
            ) * 100

        else:

            winrate = 0



        return {


            "total_trades": total,

            "wins": self.data["wins"],

            "losses": self.data["losses"],

            "winrate": round(
                winrate,
                2
            ),

            "profit": round(
                self.data["profit"],
                4
            ),

            "best_trade": self.data["best_trade"],

            "worst_trade": self.data["worst_trade"]

        }