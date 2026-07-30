import json
import os
from datetime import datetime


class TradeHistory:


    def __init__(self):

        self.file = "trade_history.json"


        if not os.path.exists(self.file):

            with open(self.file, "w") as f:

                json.dump([], f)



    def save(
        self,
        signal,
        result,
        reason,
        extra_data=None
    ):


        with open(self.file, "r") as f:

            trades = json.load(f)



        trade = {

            "time": str(datetime.now()),

            "signal": signal,

            "result": result,

            "reason": reason

        }



        if extra_data:

            trade.update(
                extra_data
            )



        trades.append(
            trade
        )



        with open(self.file, "w") as f:

            json.dump(
                trades,
                f,
                indent=4
            )



    def get_all(self):

        with open(self.file, "r") as f:

            return json.load(f)