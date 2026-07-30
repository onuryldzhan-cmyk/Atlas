"""
Atlas AI Performance Analyzer v5.1

Self Evaluation System
"""

import json
import os


class PerformanceAnalyzer:

    def __init__(self):

        self.file = "trade_memory.json"


    def load(self):

        if not os.path.exists(self.file):

            return []


        try:

            with open(
                self.file,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)


                if isinstance(data, dict):

                    return data.get(
                        "analyses",
                        []
                    )


                if isinstance(data, list):

                    return data


                return []


        except Exception:

            return []



    def analyze(self):

        trades = self.load()


        if not trades:

            return {

                "trades": 0,
                "success_rate": 50,
                "wins": 0,
                "losses": 0,
                "best_strategy": "UNKNOWN",
                "strategy_score": 50

            }


        wins = 0

        losses = 0


        strategies = {}



        for trade in trades[-500:]:


            result = trade.get(
                "result",
                "UNKNOWN"
            )


            strategy = trade.get(
                "strategy",
                "UNKNOWN"
            )


            if isinstance(strategy, dict):

                strategy = strategy.get(
                    "strategy",
                    "UNKNOWN"
                )



            if result == "WIN":

                wins += 1


            elif result == "LOSS":

                losses += 1



            if strategy not in strategies:

                strategies[strategy] = {

                    "wins": 0,
                    "losses": 0

                }



            if result == "WIN":

                strategies[strategy]["wins"] += 1


            elif result == "LOSS":

                strategies[strategy]["losses"] += 1



        total = wins + losses


        success_rate = 50


        if total > 0:

            success_rate = (
                wins / total
            ) * 100



        best_strategy = "UNKNOWN"

        best_score = 0



        for name, data in strategies.items():


            total_strategy = (

                data["wins"]

                +

                data["losses"]

            )


            if total_strategy == 0:

                continue



            score = (

                data["wins"]

                /

                total_strategy

            ) * 100



            if score > best_score:

                best_score = score

                best_strategy = name



        return {

            "trades": len(trades),

            "wins": wins,

            "losses": losses,

            "success_rate": round(
                success_rate,
                2
            ),

            "best_strategy": best_strategy,

            "strategy_score": round(
                best_score,
                2
            )

        }