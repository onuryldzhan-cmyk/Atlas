class TradeRules:


    def __init__(
        self,
        stop_loss=0.005,
        take_profit=0.01
    ):

        self.stop_loss = stop_loss
        self.take_profit = take_profit



    def calculate_levels(
        self,
        entry,
        direction
    ):

        if direction == "LONG":

            stop = entry * (1 - self.stop_loss)

            target = entry * (1 + self.take_profit)


        else:

            stop = entry * (1 + self.stop_loss)

            target = entry * (1 - self.take_profit)


        return {
            "stop_loss": round(stop,2),
            "take_profit": round(target,2)
        }



    def check_exit(
        self,
        price,
        levels,
        direction
    ):

        if direction == "LONG":

            if price <= levels["stop_loss"]:
                return "STOP LOSS"


            if price >= levels["take_profit"]:
                return "TAKE PROFIT"


        else:

            if price >= levels["stop_loss"]:
                return "STOP LOSS"


            if price <= levels["take_profit"]:
                return "TAKE PROFIT"


        return "HOLD"