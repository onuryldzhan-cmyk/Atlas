from __future__ import annotations

from datetime import datetime, UTC



class TradeMemory:


    VERSION = "1.0"



    def __init__(self):

        self.trades = []



    def remember(

        self,

        trade

    ):


        record = {


            "id":

                len(self.trades) + 1,


            "trade":

                trade,


            "created":

                datetime.now(UTC).isoformat()


        }


        self.trades.append(record)


        return record



    def get_history(self):


        return self.trades



    def count(self):


        return len(self.trades)