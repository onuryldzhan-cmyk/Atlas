class PositionManager:


    def __init__(self):

        self.positions = {}

        self.name = "Atlas Position Manager v1"



    def open_position(
        self,
        symbol,
        entry,
        size,
        stop_loss,
        take_profit,
        strategy
    ):


        self.positions[symbol] = {

            "symbol": symbol,

            "entry": entry,

            "size": size,

            "stop_loss": stop_loss,

            "take_profit": take_profit,

            "strategy": strategy,

            "status": "OPEN"

        }


        return self.positions[symbol]



    def check_position(
        self,
        symbol,
        current_price
    ):


        if symbol not in self.positions:


            return None



        position = self.positions[symbol]



        entry = position["entry"]

        pnl = (
            (current_price - entry)
            /
            entry
        ) * 100



        result = {

            "symbol": symbol,

            "entry": entry,

            "current": current_price,

            "pnl_percent": round(
                pnl,
                2
            ),

            "status": "HOLD"

        }



        if current_price <= position["stop_loss"]:


            result["status"] = "STOP_LOSS"


            position["status"] = "CLOSED"



        elif current_price >= position["take_profit"]:


            result["status"] = "TAKE_PROFIT"


            position["status"] = "CLOSED"



        return result



    def close_position(
        self,
        symbol
    ):


        if symbol in self.positions:


            self.positions[symbol]["status"] = "CLOSED"


            return self.positions[symbol]



        return None



    def get_open_positions(self):


        return {

            symbol: pos

            for symbol, pos

            in self.positions.items()

            if pos["status"] == "OPEN"

        }