import random


class MarketData:


    def __init__(self):

        self.price = 100



    def get_prices(self, count=10):

        prices = []


        for i in range(count):

            change = random.uniform(
                -1,
                1
            )


            self.price += change


            prices.append(
                round(self.price, 2)
            )


        return prices




if __name__ == "__main__":


    market = MarketData()


    data = market.get_prices(10)


    print(
        "Market Data:",
        data
    )