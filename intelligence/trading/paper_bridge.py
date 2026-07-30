"""
Atlas Paper Bridge v2.0

Paper execution adapter.

Responsibilities:

- Open paper trades
- Track positions
- Provide status
"""


from datetime import datetime, UTC



class PaperBridge:


    VERSION = "2.0"



    def __init__(self):

        self.positions = []

        self.history = []




    # ======================================
    # OPEN TRADE
    # ======================================


    def open_trade(
        self,
        symbol,
        size,
        strategy
    ):


        position = {


            "symbol":
            symbol,


            "size":
            size,


            "strategy":
            strategy,


            "mode":
            "PAPER",


            "status":
            "OPEN",


            "time":
            datetime.now(
                UTC
            ).isoformat()

        }



        self.positions.append(
            position
        )


        self.history.append(
            position
        )



        return {


            "status":
            "OPENED",


            "position":
            position

        }




    # ======================================
    # CLOSE
    # ======================================


    def close_trade(
        self,
        symbol
    ):


        for position in self.positions:


            if position["symbol"] == symbol:


                position["status"] = "CLOSED"


                self.positions.remove(
                    position
                )


                return {


                    "status":
                    "CLOSED",


                    "symbol":
                    symbol

                }



        return {


            "status":
            "FAILED",


            "reason":
            "Position not found"

        }




    # ======================================
    # POSITIONS
    # ======================================


    def get_positions(self):

        return self.positions




    # ======================================
    # STATUS
    # ======================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "mode":
            "PAPER",


            "open_positions":
            len(
                self.positions
            ),


            "history":
            len(
                self.history
            )

        }