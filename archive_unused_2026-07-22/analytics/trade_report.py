import json
import os
from datetime import datetime



class TradeReport:



    def __init__(self):

        self.trade_file = "data/atlas_memory.json"
        self.ai_file = "data/ai_decisions.json"



    def load_file(self, file):

        if not os.path.exists(file):

            return []


        try:

            with open(file, "r") as f:

                return json.load(f)

        except Exception:

            return []



    def generate(self):


        trades = self.load_file(
            self.trade_file
        )


        decisions = self.load_file(
            self.ai_file
        )



        total_trades = len(trades)

        wins = 0

        losses = 0

        profit = 0



        strategies = {

            "scalping":0,

            "trend":0,

            "reversal":0

        }



        for trade in trades:


            if trade.get("result") == "WIN":

                wins += 1


            if trade.get("result") == "LOSS":

                losses += 1



            profit += trade.get(
                "profit",
                0
            )



            strategy = trade.get(
                "strategy"
            )


            if strategy in strategies:

                strategies[strategy] += 1



        closed = wins + losses


        if closed > 0:

            win_rate = round(
                (wins / closed) * 100,
                2
            )

        else:

            win_rate = 0



        best_strategy = max(

            strategies,

            key=strategies.get

        )



        last_ai = None


        if decisions:

            last_ai = decisions[-1]



        return {


            "date":
                str(datetime.now()),


            "analysis_count":
                len(decisions),


            "trade_count":
                total_trades,


            "wins":
                wins,


            "losses":
                losses,


            "win_rate":
                win_rate,


            "profit":
                round(profit,2),


            "strategies":
                strategies,


            "best_strategy":
                best_strategy,


            "last_ai":
                last_ai

        }