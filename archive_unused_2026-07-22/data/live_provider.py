from data.binance_provider import BinanceProvider


class LiveProvider:

    def __init__(self):
        self.binance = BinanceProvider()
        print("Live Provider hazır")

    def get_candles(
        self,
        symbol,
        timeframe,
        limit=200
    ):

        return self.binance.get_candles(
            symbol=symbol,
            interval=timeframe,
            limit=limit
        )