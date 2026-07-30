"""
Atlas AI Learning Engine v6.2
Adaptive Strategy Memory + Event Learning
"""

import json
import os
import logging


logger = logging.getLogger("AtlasAI")


class LearningEngine:


    def __init__(self):

        self.file = "trade_history.json"

        self.memory_file = "market_learning.json"


        self.memory = []


        self.data = {

            "total_trades": 0,

            "wins": 0,

            "losses": 0,

            "profit": 0,


            "strategies": {

                "Trend-Follow": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "profit": 0,
                    "score": 50
                },

                "RSI-Scalping": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "profit": 0,
                    "score": 50
                },

                "Breakout": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "profit": 0,
                    "score": 50
                },

                "Momentum": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "profit": 0,
                    "score": 50
                },

                "Defensive": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "profit": 0,
                    "score": 50
                }

            }

        }


        self.load()

        self.load_memory()



    # =====================================
    # TRADE HISTORY
    # =====================================

    def load(self):

        if os.path.exists(self.file):

            try:

                with open(
                    self.file,
                    "r"
                ) as f:

                    old = json.load(f)


                self.data.update(old)


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



    # =====================================
    # MARKET MEMORY
    # =====================================

    def load_memory(self):

        if os.path.exists(
            self.memory_file
        ):

            try:

                with open(
                    self.memory_file,
                    "r"
                ) as f:

                    self.memory = json.load(f)


            except Exception:

                self.memory = []



    def save_memory(self):

        with open(
            self.memory_file,
            "w"
        ) as f:

            json.dump(
                self.memory,
                f,
                indent=4
            )



    # =====================================
    # EVENT LEARNING
    # =====================================

    def learn_market(
        self,
        symbol,
        fusion
    ):


        record = {

            "symbol": symbol,

            "fusion": fusion

        }


        self.memory.append(
            record
        )


        self.save_memory()


        logger.info(
            f"[LEARNING] Market stored: {symbol}"
        )



    # =====================================
    # STRATEGY SCORE
    # =====================================

    def get_strategy_score(
        self,
        strategy
    ):


        if strategy in self.data["strategies"]:

            return self.data["strategies"][strategy]["score"]


        return 50



    # =====================================
    # INSIGHT
    # =====================================

    def get_insight(self):


        total = self.data["total_trades"]


        win_rate = 50


        if total > 0:

            win_rate = round(
                (
                    self.data["wins"] /
                    total
                ) * 100,
                2
            )


        best = "NONE"

        score = 0


        for name,value in self.data["strategies"].items():

            if value["score"] > score:

                score = value["score"]

                best = name



        return {

            "total_trades": total,

            "wins": self.data["wins"],

            "losses": self.data["losses"],

            "win_rate": win_rate,

            "profit": self.data["profit"],

            "best_strategy": best,

            "best_score": score,

            "market_memory": len(
                self.memory
            )

        }