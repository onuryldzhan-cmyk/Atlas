from data.binance_provider import BinanceProvider


class PriceMonitor:


    def __init__(self):

        self.binance = BinanceProvider()



    def get_price(self, symbol):

        try:

            price = self.binance.get_price(
                symbol
            )

            return float(price)


        except Exception as e:

            print(
                "Fiyat alınamadı:",
                e
            )

            return None