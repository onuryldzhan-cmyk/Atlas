class TradeSimulator:

    def __init__(self):

        self.active_trade = None

    def open_trade(self, signal, entry):

        if signal == "AL":

            self.active_trade = {
                "type": "LONG",
                "entry": entry
            }

            return "ALIM AÇILDI"

        elif signal == "SAT":

            self.active_trade = {
                "type": "SHORT",
                "entry": entry
            }

            return "SATIŞ AÇILDI"

        return "İŞLEM AÇILMADI"

    def close_trade(self, exit_price):

        if self.active_trade is None:
            return None

        entry = self.active_trade["entry"]

        if self.active_trade["type"] == "LONG":
            profit = exit_price - entry
        else:
            profit = entry - exit_price

        result = {
            "type": self.active_trade["type"],
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "profit": round(profit, 2)
        }

        self.active_trade = None

        return result


if __name__ == "__main__":

    trade = TradeSimulator()

    print(trade.open_trade("AL", 100))
    print(trade.close_trade(102))

    print(trade.open_trade("SAT", 105))
    print(trade.close_trade(100))