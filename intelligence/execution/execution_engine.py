from __future__ import annotations

from datetime import datetime, UTC



class ExecutionEngine:


    VERSION = "1.0"



    def __init__(self):

        self.orders = []



    def execute(

        self,

        symbol,

        decision,

        position_size,

        strategy

    ):


        order = {


            "symbol":

                symbol,


            "action":

                decision,


            "size":

                position_size,


            "strategy":

                strategy,


            "mode":

                "PAPER",


            "status":

                "EXECUTED" if decision == "BUY" else "SKIPPED",


            "time":

                datetime.now(UTC).isoformat()

        }



        self.orders.append(order)


        return order