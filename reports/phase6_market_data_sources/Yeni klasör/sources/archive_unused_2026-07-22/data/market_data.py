import random
import time


class MarketData:
    def __init__(self):
        self.price = 100

    def get_price(self):
        change = random.uniform(-1, 1)
        self.price += change

        return round(self.price, 2)


if __name__ == "__main__":
    market = MarketData()

    for i in range(5):
        print("Anlık fiyat:", market.get_price())
        time.sleep(1)