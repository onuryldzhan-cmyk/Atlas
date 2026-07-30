import json
import os


class StrategyMemory:


    def __init__(self):

        self.file = "database/strategy_memory.json"


        if not os.path.exists(self.file):

            self.create()



    def create(self):

        data = {

            "scalping": {
                "wins":0,
                "losses":0,
                "profit":0
            },

            "trend": {
                "wins":0,
                "losses":0,
                "profit":0
            },

            "reversal": {
                "wins":0,
                "losses":0,
                "profit":0
            }

        }


        with open(self.file,"w") as f:

            json.dump(
                data,
                f,
                indent=4
            )



    def load(self):

        with open(self.file,"r") as f:

            return json.load(f)



    def update(
        self,
        strategy,
        profit
    ):


        data = self.load()


        if profit > 0:

            data[strategy]["wins"] += 1

        else:

            data[strategy]["losses"] += 1


        data[strategy]["profit"] += profit



        with open(self.file,"w") as f:

            json.dump(
                data,
                f,
                indent=4
            )


        return data



    def performance(self):

        return self.load()