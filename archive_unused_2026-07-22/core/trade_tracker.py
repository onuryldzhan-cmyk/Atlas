"""
Atlas AI Trade Tracker v6.0

Professional Trade Outcome System

Open Trade
Close Trade
Profit Calculation
Learning Feedback
"""

import json
import os
import logging

from datetime import datetime


logger = logging.getLogger("AtlasAI")



class TradeTracker:


    def __init__(
        self,
        learning_engine=None
    ):

        self.file = "active_trades.json"

        self.trades = []

        self.learning_engine = learning_engine

        self.load()



    def load(self):

        if os.path.exists(self.file):

            try:

                with open(
                    self.file,
                    "r",
                    encoding="utf-8"
                ) as f:

                    self.trades = json.load(f)

            except Exception:

                self.trades = []



    def save(self):

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(
                self.trades,
                f,
                indent=4,
                ensure_ascii=False
            )



    def open_trade(
        self,
        symbol,
        action,
        entry,
        stop_loss,
        take_profit,
        confidence,
        strategy="UNKNOWN",
        regime="UNKNOWN"
    ):


        trade = {


            "id":
            len(self.trades)+1,


            "symbol":
            symbol,


            "action":
            action,


            "entry":
            entry,


            "stop_loss":
            stop_loss,


            "take_profit":
            take_profit,


            "confidence":
            confidence,


            "strategy":
            strategy,


            "regime":
            regime,


            "status":
            "OPEN",


            "open_time":
            str(datetime.now())


        }



        self.trades.append(
            trade
        )


        self.save()


        logger.info(
            f"[TRADE] Opened {symbol}"
        )


        return trade



    def get_open_trades(self):

        return [

            x

            for x in self.trades

            if x["status"]=="OPEN"

        ]



    def calculate_profit(
        self,
        trade,
        exit_price
    ):


        entry = trade["entry"]


        if trade["action"]=="BUY":

            return exit_price-entry


        if trade["action"]=="SELL":

            return entry-exit_price


        return 0




    def close_trade(
        self,
        trade_id,
        exit_price
    ):


        for trade in self.trades:


            if trade["id"] == trade_id:


                profit = self.calculate_profit(
                    trade,
                    exit_price
                )



                trade["exit_price"] = exit_price

                trade["profit"] = round(
                    profit,
                    4
                )


                trade["status"]="CLOSED"


                trade["close_time"]=str(
                    datetime.now()
                )


                if profit > 0:

                    trade["result"]="WIN"

                elif profit < 0:

                    trade["result"]="LOSS"

                else:

                    trade["result"]="DRAW"



                self.save()



                logger.info(
                    f"[TRADE CLOSED] {trade['symbol']} {trade['result']}"
                )



                if self.learning_engine:


                    self.learning_engine.update(

                        trade["strategy"],

                        {
                            "profit":profit
                        }

                    )



                return trade



        return None