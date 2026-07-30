"""
Atlas Position Manager v12.1

Professional Position Lifecycle Engine

Responsibilities:

- Position registration
- LONG / SHORT tracking
- Dynamic PNL
- Stop Loss management
- Take Profit management
- Trailing Stop
- Position lifecycle
- Risk aware exits
- Execution integration
"""


import logging

from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.Position"
)





class PositionManager:


    VERSION = "12.1"



    def __init__(

        self,

        execution=None,

        capital=None,

        paper=None

    ):


        self.execution = execution

        self.capital = capital

        self.paper = paper



        self.positions = {}



        logger.info(
            "Atlas Position Manager v12.1 initialized"
        )





    # ==================================================
    # OPEN POSITION
    # ==================================================


    def register(

        self,

        trade

    ):


        symbol = trade["symbol"]



        if symbol in self.positions:


            return {

                "status":
                    "EXISTS",

                "symbol":
                    symbol

            }




        position = {


            "symbol":
                symbol,


            "side":
                trade.get(
                    "side",
                    "LONG"
                ),



            "entry":
                trade["price"],



            "amount":
                trade["amount"],



            "strategy":
                trade.get(
                    "strategy",
                    "UNKNOWN"
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



            "stop_loss":

                trade["price"]
                *
                0.98,



            "take_profit":

                trade["price"]
                *
                1.05,



            "highest":
                trade["price"],



            "lowest":
                trade["price"],



            "opened":

                datetime.now(
                    UTC
                ).isoformat(),



            "status":
                "OPEN"


        }



        self.positions[symbol] = position



        logger.info(

            f"[POSITION OPEN] {symbol}"

        )



        return position





    # ==================================================
    # PRICE UPDATE
    # ==================================================


    def update(

        self,

        symbol,

        price

    ):



        position = self.positions.get(
            symbol
        )



        if not position:


            return {

                "status":
                    "NOT_FOUND"

            }





        position["highest"] = max(

            position["highest"],

            price

        )



        position["lowest"] = min(

            position["lowest"],

            price

        )





        pnl = self.calculate_pnl(

            position,

            price

        )





        signal = self.check_exit(

            position,

            price,

            pnl

        )





        if signal["action"] == "CLOSE":


            self.close(

                symbol

            )





        return {


            "symbol":
                symbol,


            "price":
                price,


            "pnl":
                pnl,


            "signal":
                signal


        }







    # ==================================================
    # PNL
    # ==================================================


    def calculate_pnl(

        self,

        position,

        price

    ):


        entry = position["entry"]

        amount = position["amount"]



        if position["side"] == "SHORT":


            percent = (

                (entry-price)

                /

                entry

            ) * 100


        else:


            percent = (

                (price-entry)

                /

                entry

            ) * 100





        profit = (

            amount

            *

            percent

            /

            100

        )



        return {


            "percent":

                round(
                    percent,
                    3
                ),



            "profit":

                round(
                    profit,
                    2
                )

        }





    # ==================================================
    # EXIT ENGINE
    # ==================================================


    def check_exit(

        self,

        position,

        price,

        pnl

    ):


        percent = pnl["percent"]





        if percent <= -2:


            return {

                "action":
                    "CLOSE",


                "reason":
                    "STOP_LOSS"

            }





        if percent >= 5:


            return {


                "action":
                    "CLOSE",


                "reason":
                    "TAKE_PROFIT"

            }





        highest = position["highest"]



        trailing = (

            (highest-price)

            /

            highest

        ) * 100





        if trailing >= 1.5:


            return {


                "action":
                    "CLOSE",


                "reason":
                    "TRAILING_STOP"

            }





        return {


            "action":
                "HOLD"

        }







    # ==================================================
    # CLOSE POSITION
    # ==================================================


    def close(

        self,

        symbol

    ):


        position = self.positions.pop(

            symbol,

            None

        )



        if not position:


            return None




        logger.info(

            f"[POSITION CLOSED] {symbol}"

        )



        if self.capital:


            self.capital.close_position(

                symbol

            )



        return position






    # ==================================================
    # GET POSITION
    # ==================================================


    def get(

        self,

        symbol

    ):


        return self.positions.get(

            symbol

        )





    # ==================================================
    # STATUS
    # ==================================================


    def status(

        self

    ):


        return {


            "version":

                self.VERSION,



            "open_positions":

                len(
                    self.positions
                ),



            "positions":

                list(
                    self.positions.keys()
                )

        }