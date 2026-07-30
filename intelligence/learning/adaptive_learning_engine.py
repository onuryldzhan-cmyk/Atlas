from __future__ import annotations

from datetime import datetime, UTC



class AdaptiveLearningEngine:


    VERSION = "1.0"



    def __init__(self):

        self.strategy_memory = {}



    def register_trade(

        self,

        strategy,

        profit

    ):


        if strategy not in self.strategy_memory:


            self.strategy_memory[strategy] = {

                "trades": 0,

                "wins": 0,

                "losses": 0,

                "profit": 0

            }



        memory = self.strategy_memory[strategy]


        memory["trades"] += 1


        memory["profit"] += profit



        if profit > 0:

            memory["wins"] += 1


        else:

            memory["losses"] += 1



        return memory



    def evaluate_strategy(

        self,

        strategy

    ):


        if strategy not in self.strategy_memory:

            return {


                "strategy":

                    strategy,


                "status":

                    "NO_DATA"

            }



        data = self.strategy_memory[strategy]



        win_rate = (

            data["wins"] /

            data["trades"]

        ) * 100



        if win_rate >= 60:


            status = "INCREASE_WEIGHT"



        elif win_rate < 40:


            status = "DECREASE_WEIGHT"



        else:


            status = "KEEP"



        return {


            "strategy":

                strategy,


            "win_rate":

                round(win_rate,2),


            "status":

                status,


            "data":

                data,


            "time":

                datetime.now(UTC).isoformat()

        }