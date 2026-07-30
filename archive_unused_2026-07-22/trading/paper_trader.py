from position.position_manager import PositionManager


class PaperTrader:


    def __init__(self):

        self.position_manager = PositionManager()

        self.positions = {}

        self.history = []



    def buy(
        self,
        symbol,
        price,
        metadata=None
    ):


        if symbol in self.positions:

            return {
                "error": "Bu coin zaten açık."
            }



        size = round(
            30 / price,
            6
        )


        stop_loss = round(
            price * 0.99,
            2
        )


        take_profit = round(
            price * 1.01,
            2
        )



        position = {

            "action": "BUY",

            "symbol": symbol,

            "entry": price,

            "size": size,

            "stop_loss": stop_loss,

            "take_profit": take_profit,

            "metadata": metadata

        }



        self.positions[symbol] = position



        self.position_manager.open_position(

            symbol,

            price,

            size,

            stop_loss,

            take_profit,

            metadata

        )



        self.history.append(position)



        print(
            "Pozisyon açıldı:",
            position
        )



        return position





    def sell(
        self,
        symbol,
        price
    ):


        if symbol not in self.positions:


            return {
                "error": "Açık pozisyon yok."
            }



        position = self.positions[symbol]


        pnl = (

            (price - position["entry"])

            /

            position["entry"]

        ) * 100



        result = {

            "action": "SELL",

            "symbol": symbol,

            "entry": position["entry"],

            "exit": price,

            "pnl_percent": round(
                pnl,
                2
            )

        }



        del self.positions[symbol]


        self.history.append(result)



        print(
            "Pozisyon kapandı:",
            result
        )


        return result





    def monitor(
        self,
        symbol,
        price
    ):


        result = self.position_manager.check_position(

            symbol,

            price

        )


        return result





    def check_positions(
        self,
        prices
    ):


        results = []


        for symbol, price in prices.items():


            result = self.monitor(

                symbol,

                price

            )


            if result:

                results.append(result)



        return results





    def get_positions(self):


        return self.positions