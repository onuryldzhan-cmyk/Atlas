import json
import os


class AIPerformance:


    def __init__(self):

        self.file = "database/ai_performance.json"


        if not os.path.exists(self.file):

            self.create()



    def create(self):

        data = {

            "total_tests": 0,

            "wins": 0,

            "losses": 0,

            "strategies": {

                "scalping": {
                    "tests": 0,
                    "wins": 0,
                    "losses": 0
                },

                "trend": {
                    "tests": 0,
                    "wins": 0,
                    "losses": 0
                },

                "reversal": {
                    "tests": 0,
                    "wins": 0,
                    "losses": 0
                }

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



    def add_result(
        self,
        strategy,
        result
    ):

        data = self.load()


        data["total_tests"] += 1


        if result == "WIN":

            data["wins"] += 1

        else:

            data["losses"] += 1



        if strategy in data["strategies"]:

            data["strategies"][strategy]["tests"] += 1


            if result == "WIN":

                data["strategies"][strategy]["wins"] += 1

            else:

                data["strategies"][strategy]["losses"] += 1



        with open(self.file,"w") as f:

            json.dump(
                data,
                f,
                indent=4
            )


        return data



    def report(self):

        return self.load()