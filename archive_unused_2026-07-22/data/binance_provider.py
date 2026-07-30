from binance.client import Client


class BinanceProvider:

    def __init__(self):
        self.client = Client()
        print("Binance bağlantısı kuruldu.")

    def get_price(self, symbol="BTCUSDT"):

        data = self.client.get_symbol_ticker(symbol=symbol)

        return float(data["price"])

    def get_candles(
        self,
        symbol="BTCUSDT",
        interval=Client.KLINE_INTERVAL_5MINUTE,
        limit=200
    ):

        klines = self.client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit
        )

        candles = []

        for k in klines:

            candles.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5])
            })

        return candles


if __name__ == "__main__":

    provider = BinanceProvider()

    print(provider.get_price())
    print(provider.get_candles(limit=3))