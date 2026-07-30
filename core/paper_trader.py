"""
============================================================
ATLAS PAPER TRADER v11.0
============================================================

Professional Paper Execution Engine


Responsibilities
----------------

- Simulated BUY execution
- Simulated SELL execution
- Position management
- Balance tracking
- Trade history
- PnL calculation
- ExecutionManager integration
- Persistent storage


Pipeline


Decision

   |

ExecutionManager

   |

PaperTrader

   |

Portfolio


============================================================
"""


from __future__ import annotations


import json
import os
import logging


from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.PaperTrader"
)





class PaperTrader:


    VERSION = "11.0"



    def __init__(

        self,

        capital=None,

        database=None,

        filename="paper_trades.json"

    ):


        self.capital = capital

        self.database = database

        self.filename = filename


        self.balance = 10000.0


        self.positions = {}

        self.history = []


        self.load()



        logger.info(
            "Paper Trader v%s initialized",
            self.VERSION
        )






    # ==================================================
    # EXECUTION ENTRY
    # ==================================================


    def execute(

        self,

        request

    ):


        symbol = request.get(
            "symbol"
        )


        action = request.get(
            "action"
        )


        price = request.get(
            "price",
            0
        )



        if not symbol or not price:


            return {

                "status":
                "FAILED",

                "reason":
                "Invalid request"

            }




        if action == "BUY":


            return self.open_trade(

                symbol,

                price

            )



        elif action == "SELL":


            return self.close_trade(

                symbol

            )



        return {


            "status":
            "IGNORED",

            "reason":
            "Unsupported action"


        }







    # ==================================================
    # OPEN POSITION
    # ==================================================


    def open_trade(

        self,

        symbol,

        price,

        amount=100

    ):



        if symbol in self.positions:


            return {

                "status":
                "FAILED",

                "reason":
                "Position exists"

            }



        position = {


            "symbol":

            symbol,


            "entry_price":

            price,


            "current_price":

            price,


            "amount":

            amount,


            "opened":

            datetime.now(
                UTC
            ).isoformat()


        }



        self.positions[symbol]=position



        self.history.append({

            "type":
            "BUY",

            "symbol":
            symbol,

            "price":
            price,

            "time":
            datetime.now(
                UTC
            ).isoformat()

        })



        self.save()



        logger.info(

            "[PAPER BUY] %s %.4f",

            symbol,

            price

        )



        return {


            "status":
            "OPENED",


            "position":
            position


        }







    # ==================================================
    # CLOSE POSITION
    # ==================================================


    def close_trade(

        self,

        symbol

    ):


        if symbol not in self.positions:


            return {

                "status":
                "FAILED",

                "reason":
                "No position"

            }



        position=self.positions.pop(
            symbol
        )



        profit=self.calculate_profit(
            position
        )



        self.history.append({

            "type":
            "SELL",

            "symbol":
            symbol,

            "profit":
            profit,

            "time":
            datetime.now(
                UTC
            ).isoformat()

        })


        self.save()



        logger.info(

            "[PAPER SELL] %s profit=%s",

            symbol,

            profit

        )



        return {


            "status":
            "CLOSED",

            "profit":
            profit


        }







    # ==================================================
    # PRICE UPDATE
    # ==================================================


    def update_price(

        self,

        symbol,

        price

    ):


        if symbol in self.positions:


            self.positions[symbol][

                "current_price"

            ] = price



            self.save()







    # ==================================================
    # PROFIT
    # ==================================================


    def calculate_profit(

        self,

        position

    ):


        return round(

            position["current_price"]

            -

            position["entry_price"],

            4

        )







    # ==================================================
    # STORAGE
    # ==================================================


    def load(self):


        if not os.path.exists(
            self.filename
        ):

            return



        try:


            with open(

                self.filename,

                "r"

            ) as f:


                data=json.load(f)


                self.positions=data.get(
                    "positions",
                    {}
                )


                self.history=data.get(
                    "history",
                    []
                )



        except Exception:


            logger.exception(
                "Paper load failed"
            )







    def save(self):


        with open(

            self.filename,

            "w"

        ) as f:


            json.dump(

                {

                "positions":
                self.positions,


                "history":
                self.history


                },

                f,

                indent=4

            )







    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "balance":
            self.balance,


            "positions":
            len(
                self.positions
            ),


            "trades":
            len(
                self.history
            )

        }