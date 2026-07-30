class ProfitCalculator:


    def calculate(self, signal, entry_price, exit_price, amount):


        if signal == "AL":

            change = exit_price - entry_price


        elif signal == "SAT":

            change = entry_price - exit_price


        else:

            return 0



        profit = (change / entry_price) * amount


        return round(profit, 2)