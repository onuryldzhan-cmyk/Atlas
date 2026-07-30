import random


class CandleData:


    def generate_candle(self, previous_close=100):

        open_price = previous_close


        high_price = open_price + random.uniform(0, 1)

        low_price = open_price - random.uniform(0, 1)

        close_price = random.uniform(
            low_price,
            high_price
        )


        volume = random.randint(
            1000,
            10000
        )


        candle = {

            "open": round(open_price, 2),

            "high": round(high_price, 2),

            "low": round(low_price, 2),

            "close": round(close_price, 2),

            "volume": volume

        }


        return candle



if __name__ == "__main__":

    data = CandleData()

    candle = data.generate_candle()

    print(candle)