class AutoManager:


    def __init__(self, execution):

        self.execution = execution



    def check(
        self,
        symbol,
        price
    ):


        trader = self.execution.paper



        if symbol not in trader.positions:

            return None



        result = trader.monitor(

            symbol,

            price

        )



        if result["status"] == "STOP_LOSS":


            return {


                "action": "AUTO SELL",

                "reason": "STOP LOSS",

                "result": self.execution.execute(

                    "SELL",

                    symbol,

                    price,

                    0.0005,

                    {

                        "reason": "STOP LOSS"

                    }

                )

            }





        if result["status"] == "TAKE_PROFIT":


            return {


                "action": "AUTO SELL",

                "reason": "TAKE PROFIT",

                "result": self.execution.execute(

                    "SELL",

                    symbol,

                    price,

                    0.0005,

                    {

                        "reason": "TAKE PROFIT"

                    }

                )

            }





        return result