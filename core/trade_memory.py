"""
============================================================
ATLAS AI TRADE MEMORY ENGINE v1.0
============================================================

Purpose:

Long term trading experience storage.

Responsibilities:

- Store executed trades
- Store outcomes
- Track strategy performance
- Provide learning data


Pipeline:

Execution
    |
Trade Memory
    |
Outcome Analysis
    |
Learning Engine


============================================================
"""


from __future__ import annotations


import json
import logging


from pathlib import Path


from datetime import datetime, UTC




logger = logging.getLogger(
    "AtlasAI.TradeMemory"
)





class TradeMemory:


    VERSION = "1.0"


    DATABASE = "trade_memory.json"





    def __init__(

        self,

        storage="database"

    ):


        self.storage = Path(
            storage
        )


        self.storage.mkdir(

            parents=True,

            exist_ok=True

        )


        self.file = (

            self.storage /

            self.DATABASE

        )


        self.trades = []


        self.load()



        logger.info(

            "Trade Memory v1.0 initialized"

        )






    # =====================================================
    # LOAD
    # =====================================================


    def load(self):


        if not self.file.exists():

            return



        try:


            with open(

                self.file,

                "r",

                encoding="utf-8"

            ) as f:


                data = json.load(f)



            self.trades = data.get(

                "trades",

                []

            )


        except Exception:


            logger.exception(

                "Trade memory load failed"

            )








    # =====================================================
    # SAVE
    # =====================================================


    def save(self):


        data = {


            "version":

            self.VERSION,


            "trades":

            self.trades,


            "updated":

            datetime.now(

                UTC

            ).isoformat()

        }



        with open(

            self.file,

            "w",

            encoding="utf-8"

        ) as f:


            json.dump(

                data,

                f,

                indent=4,

                ensure_ascii=False

            )







    # =====================================================
    # REMEMBER TRADE
    # =====================================================


    def remember(

        self,

        trade:dict

    ):


        record = {


            "id":

            trade.get(

                "execution_id"

            ),


            "symbol":

            trade.get(

                "symbol"

            ),


            "side":

            trade.get(

                "side"

            ),


            "strategy":

            trade.get(

                "strategy",

                "Atlas"

            ),


            "confidence":

            trade.get(

                "confidence",

                0

            ),


            "risk":

            trade.get(

                "risk",

                "MEDIUM"

            ),


            "entry":

            trade.get(

                "price",

                0

            ),


            "amount":

            trade.get(

                "amount",

                0

            ),


            "result":

            None,


            "pnl":

            None,


            "created":

            datetime.now(

                UTC

            ).isoformat()


        }



        self.trades.append(

            record

        )


        self.save()



        return record







    # =====================================================
    # UPDATE RESULT
    # =====================================================


    def update_result(

        self,

        trade_id,

        pnl

    ):


        for trade in self.trades:


            if trade["id"] == trade_id:



                trade["pnl"] = pnl



                trade["result"] = (

                    "WIN"

                    if pnl > 0

                    else

                    "LOSS"

                )



                trade["closed"] = datetime.now(

                    UTC

                ).isoformat()



                self.save()



                return trade



        return None







    # =====================================================
    # STATISTICS
    # =====================================================


    def statistics(self):


        total = len(

            self.trades

        )


        wins = len(

            [

            t for t in self.trades

            if t.get("result") == "WIN"

            ]

        )


        losses = len(

            [

            t for t in self.trades

            if t.get("result") == "LOSS"

            ]

        )



        win_rate = 0



        if total:

            win_rate = round(

                wins /

                total *

                100,

                2

            )



        return {


            "total":

            total,


            "wins":

            wins,


            "losses":

            losses,


            "win_rate":

            win_rate

        }







    # =====================================================
    # STRATEGY ANALYSIS
    # =====================================================


    def strategy_score(

        self,

        strategy

    ):


        trades = [


            t for t in self.trades

            if t.get(

                "strategy"

            ) == strategy


        ]



        if not trades:

            return 0



        wins = len(

            [

            t for t in trades

            if t.get("result")

            ==

            "WIN"

            ]

        )



        return round(

            wins /

            len(trades)

            *

            100,

            2

        )







    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "stored_trades":

            len(

                self.trades

            ),


            "statistics":

            self.statistics(),


            "database":

            str(

                self.file

            )

        }