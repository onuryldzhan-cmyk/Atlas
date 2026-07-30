"""
Atlas AI Paper Execution Engine v1.0

Simulated execution layer.

Responsibilities:

- Receive validated decisions
- Open virtual positions
- Close virtual positions
- Track PnL
- Create trade records


Does NOT:
- send real orders
- connect exchange
- manage strategy


"""


from datetime import datetime, timezone



class PaperExecutor:


    VERSION = "1.0"



    def __init__(
        self,
        starting_balance=10000
    ):


        self.balance = starting_balance

        self.positions = {}

        self.history = []


        print(
            "[EXECUTION] Paper Executor v1.0 initialized"
        )





    # =================================================
    # EXECUTE
    # =================================================


    def execute(
        self,
        decision,
        price
    ):


        if not decision.is_trade_signal():

            return {

                "status":
                    "IGNORED",

                "reason":
                    "No trade signal"

            }




        if decision.action.value == "BUY":


            return self.open_position(

                decision,

                price

            )





        if decision.action.value == "SELL":


            return self.close_position(

                decision,

                price

            )







    # =================================================
    # OPEN POSITION
    # =================================================


    def open_position(
        self,
        decision,
        price
    ):


        symbol = decision.symbol



        if symbol in self.positions:


            return {

                "status":
                    "REJECTED",

                "reason":
                    "Position already exists"

            }



        amount = (

            self.balance * 0.10

        )



        self.positions[symbol] = {


            "symbol":
                symbol,


            "entry_price":
                price,


            "amount":
                amount,


            "opened":

                datetime.now(
                    timezone.utc
                ).isoformat()

        }



        record = {


            "type":
                "OPEN",


            "symbol":
                symbol,


            "price":
                price,


            "time":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }



        self.history.append(
            record
        )



        print(

            f"[EXECUTION] OPEN {symbol} @ {price}"

        )



        return {


            "status":
                "OPENED",


            "position":
                self.positions[symbol]

        }







    # =================================================
    # CLOSE POSITION
    # =================================================


    def close_position(
        self,
        decision,
        price
    ):


        symbol = decision.symbol



        if symbol not in self.positions:


            return {

                "status":
                    "REJECTED",

                "reason":
                    "No position"

            }




        position = self.positions.pop(
            symbol
        )



        pnl = (

            price -

            position["entry_price"]

        ) / position["entry_price"] * 100




        self.balance += (

            position["amount"]

            *

            pnl / 100

        )



        record = {


            "type":
                "CLOSE",


            "symbol":
                symbol,


            "entry":
                position["entry_price"],


            "exit":
                price,


            "pnl_percent":
                round(
                    pnl,
                    3
                ),


            "time":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }



        self.history.append(
            record
        )



        print(

            f"[EXECUTION] CLOSE {symbol} PNL {pnl:.2f}%"

        )



        return {


            "status":
                "CLOSED",


            "pnl":
                pnl

        }







    # =================================================
    # STATUS
    # =================================================


    def status(self):


        return {


            "version":
                self.VERSION,


            "balance":
                self.balance,


            "positions":
                self.positions,


            "trades":
                len(
                    self.history
                )

        }