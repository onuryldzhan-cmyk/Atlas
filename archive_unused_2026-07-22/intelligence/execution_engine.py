from exchange.exchange_adapter import ExchangeAdapter



class ExecutionEngine:


    def __init__(self):

        self.exchange = ExchangeAdapter()

        print(
            "Execution Engine hazır"
        )



    def execute(
        self,
        decision,
        symbol,
        price,
        amount,
        metadata=None
    ):


        if decision != "BUY" and decision != "SELL":

            return {

                "status": "NO_ACTION",

                "reason": "Karar işlem gerektirmiyor"

            }



        order = self.exchange.place_order(

            symbol,

            decision.lower(),

            amount

        )


        return {


            "action": decision,

            "symbol": symbol,

            "price": price,

            "amount": amount,

            "metadata": metadata,

            "exchange_result": order


        }