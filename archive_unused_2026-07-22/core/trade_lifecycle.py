"""
Atlas AI Trade Lifecycle v4.2
Advanced Position Monitoring
SL / TP / Learning Connector
"""


import time


class TradeLifecycle:


    def __init__(
        self,
        portfolio,
        learning,
        strategy,
        database=None
    ):

        self.portfolio = portfolio
        self.learning = learning
        self.strategy = strategy
        self.database = database



    def calculate_profit(
        self,
        action,
        entry,
        current,
        size
    ):

        if action == "BUY":

            return (
                current - entry
            ) * size


        elif action == "SELL":

            return (
                entry - current
            ) * size


        return 0



    def check_positions(
        self,
        prices
    ):


        closed = []


        positions = (
            self.portfolio.get_open_positions()
        )


        for position in positions:


            symbol = position.get(
                "symbol"
            )


            if symbol not in prices:

                continue



            current_price = prices[symbol]


            entry = position.get(
                "entry",
                0
            )


            size = position.get(
                "size",
                0
            )


            stop = position.get(
                "stop_loss",
                0
            )


            target = position.get(
                "take_profit",
                0
            )


            action = position.get(
                "action"
            )



            reason = None



            if action == "BUY":


                if current_price <= stop:

                    reason = "STOP_LOSS"


                elif current_price >= target:

                    reason = "TAKE_PROFIT"




            elif action == "SELL":


                if current_price >= stop:

                    reason = "STOP_LOSS"


                elif current_price <= target:

                    reason = "TAKE_PROFIT"





            if reason:



                profit = self.calculate_profit(

                    action,

                    entry,

                    current_price,

                    size

                )



                trade_result = {


                    "symbol":
                        symbol,


                    "action":
                        action,


                    "entry":
                        entry,


                    "exit":
                        current_price,


                    "size":
                        size,


                    "profit":
                        round(
                            profit,
                            4
                        ),


                    "reason":
                        reason,


                    "time":
                        time.time()


                }



                self.portfolio.remove_position(

                    symbol,

                    profit

                )




                self.learning.update(

                    action,

                    trade_result

                )




                self.strategy.update(

                    "Trend-Follow",

                    profit

                )




                if self.database:


                    try:

                        self.database.save_trade(
                            trade_result
                        )


                    except Exception:

                        pass




                closed.append(
                    trade_result
                )



        return closed