"""
Atlas AI Adaptive Learning v4.6

Self Improving Strategy Weight System
"""

import json
import os


class AdaptiveLearning:


    def __init__(self):

        self.file = "adaptive_learning.json"


        self.data = {

            "strategies": {

                "Trend-Follow": {
                    "trades": 0,
                    "wins": 0,
                    "profit": 0
                },

                "RSI-Scalping": {
                    "trades": 0,
                    "wins": 0,
                    "profit": 0
                },

                "Breakout": {
                    "trades": 0,
                    "wins": 0,
                    "profit": 0
                },

                "Momentum": {
                    "trades": 0,
                    "wins": 0,
                    "profit": 0
                },

                "Defensive": {
                    "trades": 0,
                    "wins": 0,
                    "profit": 0
                }

            }

        }


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

                pass




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





    def update(
        self,
        strategy,
        profit
    ):


        if strategy not in self.data["strategies"]:

            return



        memory = self.data["strategies"][strategy]


        memory["trades"] += 1


        memory["profit"] += profit



        if profit > 0:

            memory["wins"] += 1



        self.save()





    def get_score(
        self,
        strategy
    ):


        if strategy not in self.data["strategies"]:

            return 50



        data = self.data["strategies"][strategy]


        trades = data["trades"]



        if trades == 0:

            return 50



        win_rate = (

            data["wins"] /
            trades

        ) * 100



        profit_bonus = 0



        if data["profit"] > 0:

            profit_bonus = 10


        elif data["profit"] < 0:

            profit_bonus = -10



        score = (

            win_rate +
            profit_bonus

        )



        if score > 100:

            score = 100


        if score < 0:

            score = 0



        return round(
            score,
            2
        )





    def best_strategy(self):


        best = None

        best_score = 0



        for strategy in self.data["strategies"]:


            score = self.get_score(
                strategy
            )


            if score > best_score:


                best_score = score

                best = strategy



        return {

            "strategy": best,

            "score": best_score

        }