from config.settings import MODE
from trading.paper_trader import PaperTrader


class ExecutionManager:


    def __init__(self):

        self.mode = MODE

        self.paper = PaperTrader()


        print(
            f"Execution Manager hazır | Mod: {self.mode}"
        )



    def execute(
        self,
        action,
        symbol,
        price,
        size,
        metadata=None
    ):


        # TEST MODU

        if self.mode == "TEST":


            if action == "BUY":


                return self.paper.buy(

                    symbol,

                    price,

                    metadata

                )



            elif action == "SELL":


                if symbol not in self.paper.positions:


                    return {

                        "error":
                        "SELL için açık pozisyon yok."

                    }



                return self.paper.sell(

                    symbol,

                    price

                )



        # LIVE MODU

        elif self.mode == "LIVE":


            return {


                "error":
                "LIVE emir sistemi hazır değil."

            }



        return {


            "error":
            "Bilinmeyen mod."

        }




    def get_positions(
        self
    ):


        return self.paper.get_positions()